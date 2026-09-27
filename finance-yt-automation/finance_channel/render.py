"""Scene-by-scene video assembly with ffmpeg.

For every scene:
  1. synthesize its narration (word-timed),
  2. build its visual (animated chart, stat card, or footage/gradient),
  3. burn in captions and mux the voiceover into a segment of exactly the
     narration's length.
Segments share codec, resolution, fps, and audio format, so they are joined
with the concat demuxer. Optional background music is mixed in at the end.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import charts
from .captions import build_ass, subtitles_filter
from .config import Config
from .footage import fetch_clip
from .schemas import VideoPlan
from .tts import synthesize
from .utils import ffprobe_duration, log, require_ffmpeg, run

TAIL_PAD = 0.25       # seconds of breathing room after each scene
CHART_REVEAL = 2.4    # seconds for a chart to draw itself


@dataclass
class RenderedScene:
    index: int
    section: str
    start: float
    duration: float
    path: Path


@dataclass
class RenderResult:
    video_path: Path
    scenes: list[RenderedScene]
    duration: float


def render_plan(
    plan: VideoPlan, *, config: Config, video_format: str, stem: str,
    allow_silent_fallback: bool = False,
) -> RenderResult:
    require_ffmpeg()
    w, h, fps = config.frame_size(video_format)
    work = config.workdir / "work" / stem
    work.mkdir(parents=True, exist_ok=True)
    theme = config.get("visuals.chart_theme") or {}
    symbol = config.get("channel.currency_symbol", "$")
    orientation = "portrait" if h > w else "landscape"
    hf_budget = int(config.get("visuals.higgsfield_max_clips", 3))

    rendered: list[RenderedScene] = []
    t = 0.0
    for i, scene in enumerate(plan.scenes):
        log(f"[{i + 1}/{len(plan.scenes)}] {scene.kind}: {scene.narration[:60]}...", level="step")
        sdir = work / f"scene{i:02d}"
        sdir.mkdir(parents=True, exist_ok=True)

        audio, words = synthesize(scene.narration, sdir / "voice.mp3", config=config,
                                  allow_silent_fallback=allow_silent_fallback)
        dur = ffprobe_duration(audio) + TAIL_PAD

        caption_pos = None
        if scene.kind == "chart" and scene.chart:
            data = charts.compute_chart(scene.chart, symbol)
            frames = charts.render_chart_frames(data, sdir / "frames", width=w, height=h,
                                                theme=theme, symbol=symbol)
            reveal = min(CHART_REVEAL, dur * 0.6)
            visual = ["-framerate", f"{len(frames) / reveal:.4f}", "-i", str(sdir / "frames" / "f_%03d.png")]
            vchain = (f"[0:v]fps={fps},tpad=stop_mode=clone:stop_duration={dur:.3f},"
                      f"scale={w}:{h},setsar=1")
            caption_pos = "bottom"
        elif scene.kind == "stat" and scene.stat:
            card = charts.render_stat_card(scene.stat, sdir / "stat.png", width=w, height=h, theme=theme)
            visual = ["-loop", "1", "-framerate", str(fps), "-i", str(card)]
            vchain = (f"[0:v]scale={w}:{h},setsar=1,fade=t=in:st=0:d=0.3")
            caption_pos = "bottom"
        else:
            clip = None
            if scene.footage_query:
                paid_ok = hf_budget > 0
                clip = fetch_clip(scene.footage_query, config=config, orientation=orientation,
                                  dest_dir=config.workdir / "footage", allow_paid=paid_ok)
                if clip and config.get("visuals.footage_source") == "higgsfield":
                    hf_budget -= 1
            if clip:
                visual = ["-stream_loop", "-1", "-i", str(clip)]
                vchain = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                          f"setsar=1,fps={fps},drawbox=color=black@0.35:t=fill")
            else:
                bg = sdir / "bg.png"
                if not bg.exists():
                    charts.render_gradient(bg, width=w, height=h, theme=theme)
                visual = ["-loop", "1", "-framerate", str(fps), "-i", str(bg)]
                vchain = f"[0:v]scale={w}:{h},setsar=1"

        filters = vchain
        if config.get("captions.enabled", True) and words:
            ass = build_ass(words, sdir / "captions.ass", config=config, width=w, height=h,
                            position=caption_pos)
            filters += "," + subtitles_filter(ass)
        filters += f",format=yuv420p[v];[1:a]apad=pad_dur={TAIL_PAD},aresample=44100[a]"

        out = sdir / "segment.mp4"
        run([
            "ffmpeg", "-y", *visual, "-i", str(audio),
            "-filter_complex", filters,
            "-map", "[v]", "-map", "[a]",
            "-t", f"{dur:.3f}", "-r", str(fps),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100",
            str(out),
        ])
        real = ffprobe_duration(out)
        rendered.append(RenderedScene(index=i, section=scene.section, start=t, duration=real, path=out))
        t += real

    out_dir = config.workdir / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{stem}.mp4"
    _concat([r.path for r in rendered], final, work)
    _mix_music(final, config)
    total = ffprobe_duration(final)
    if video_format == "short" and total > float(config.get("video.short.max_duration_sec", 59)):
        log(f"Short runs {total:.1f}s; YouTube treats videos over 60s as long-form.", level="warn")
    log(f"Rendered {final.name} ({total:.1f}s)", level="ok")
    return RenderResult(video_path=final, scenes=rendered, duration=total)


def _concat(segments: list[Path], out: Path, work: Path) -> None:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
    try:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-movflags", "+faststart", str(out)])
    except RuntimeError:
        log("Stream-copy concat failed; re-encoding.", level="warn")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])


def _mix_music(video: Path, config: Config) -> None:
    track = config.get("audio.background_music")
    if not track:
        return
    track_path = Path(track)
    if not track_path.exists():
        log(f"Background music not found: {track}", level="warn")
        return
    vol = float(config.get("audio.music_volume", 0.08))
    tmp = video.with_suffix(".music.mp4")
    run([
        "ffmpeg", "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(track_path),
        "-filter_complex",
        f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(tmp),
    ])
    shutil.move(str(tmp), str(video))


def build_chapters(scenes: list[RenderedScene], *, min_len: float = 10.0) -> list[tuple[float, str]]:
    """YouTube chapters from scene sections.

    Consecutive scenes with the same section merge. YouTube needs the first
    chapter at 0:00, at least 3 chapters, and each at least 10 seconds; short
    chapters are folded into the previous one. Returns [] if that's impossible.
    """
    merged: list[list] = []
    for s in scenes:
        label = (s.section or "").strip() or "Intro"
        if merged and merged[-1][1].lower() == label.lower():
            merged[-1][2] += s.duration
        else:
            merged.append([s.start, label, s.duration])
    folded = merged
    i = 0
    while i < len(folded) and len(folded) > 1:
        if folded[i][2] >= min_len:
            i += 1
        elif i == 0:                      # short opener absorbs the next chapter
            folded[0][2] += folded[1][2]
            del folded[1]
        else:                             # short chapter folds into the previous one
            folded[i - 1][2] += folded[i][2]
            del folded[i]
    if len(folded) < 3:
        return []
    folded[0][0] = 0.0
    return [(start, label) for start, label, _ in folded]
