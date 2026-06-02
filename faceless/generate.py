"""From-scratch ('generate') video assembly.

Given a script, this:
  1. synthesizes a voiceover (TTS) with word timing,
  2. acquires a background (stock footage or a solid color),
  3. burns in captions over the background,
  4. muxes the voiceover, and writes the final MP4.
"""

from __future__ import annotations

from pathlib import Path

from .captions import build_srt, subtitles_filter
from .config import Config
from .llm import ScriptResult
from .montage import build_background
from .sources import fetch_stock_clips
from .tts import synthesize
from .utils import ffprobe_duration, log, require_ffmpeg, run, slugify, timestamp_slug


def generate_video(
    script: ScriptResult,
    *,
    config: Config,
    video_format: str,
) -> Path:
    """Render a faceless video from a script. Returns the output path."""
    require_ffmpeg()
    workdir = config.workdir
    w = config.get(f"video.{video_format}.width", 1080 if video_format == "short" else 1920)
    h = config.get(f"video.{video_format}.height", 1920 if video_format == "short" else 1080)
    fps = config.get(f"video.{video_format}.fps", 30)

    stem = f"{timestamp_slug()}-{slugify(script.title_idea)}"

    # 1. Voiceover -------------------------------------------------------
    audio_path = workdir / "audio" / f"{stem}.mp3"
    audio_path, segments = synthesize(script.script, audio_path, config=config)
    duration = ffprobe_duration(audio_path)

    # 2. Captions --------------------------------------------------------
    subs = None
    if config.get("captions.enabled", True):
        srt = build_srt(segments, workdir / "captions" / f"{stem}.srt")
        subs = subtitles_filter(srt, config, video_format)

    # 3. Background ------------------------------------------------------
    # Fetch enough clips to cover the audio as a montage (one clip per
    # segment_sec), capped by generate.montage_clips.
    orientation = "portrait" if video_format == "short" else "landscape"
    seg_dur = float(config.get("generate.segment_sec", 5))
    montage_on = config.get("generate.montage", True)
    max_clips = int(config.get("generate.montage_clips", 6)) if montage_on else 1
    wanted = max(1, min(max_clips, int(duration // seg_dur) + 1))
    keywords = script.on_screen_keywords or [script.title_idea]
    clips = fetch_stock_clips(
        keywords, config=config, count=wanted, orientation=orientation,
    )

    out_dir = workdir / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.mp4"

    bg = build_background(clips, config=config, video_format=video_format, stem=stem)

    if bg:
        log(f"Compositing over background: {bg.name}", level="step")
        video_chain = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1"
        )
        inputs = ["-stream_loop", "-1", "-i", str(bg), "-i", str(audio_path)]
        audio_map = "1:a"
    else:
        color = _hexcolor(config.get("generate.fallback_color", "#101418"))
        log("No footage — using solid background.", level="step")
        video_chain = f"[0:v]null"
        inputs = [
            "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}",
            "-i", str(audio_path),
        ]
        audio_map = "1:a"

    if subs:
        filter_complex = f"{video_chain}[pre];[pre]{subs}[v]"
    else:
        filter_complex = f"{video_chain}[v]"

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", audio_map,
        "-t", f"{duration:.3f}",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_path),
    ]
    run(cmd)
    log(f"Rendered: {out_path.name} ({duration:.1f}s)", level="ok")
    return out_path


def _hexcolor(value: str) -> str:
    """Convert '#101418' to ffmpeg's '0x101418' (pass through named colors)."""
    value = value.strip()
    if value.startswith("#"):
        return "0x" + value[1:]
    return value
