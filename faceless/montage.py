"""Stitch multiple stock clips into a single background montage.

Each source clip is normalized (scaled/cropped to the target frame, fixed fps,
trimmed, audio stripped) so they share identical parameters, then concatenated.
The result is a silent background video that `generate` loops under the
voiceover and captions.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .utils import log, run, slugify


def build_background(
    clips: list[Path],
    *,
    config: Config,
    video_format: str,
    stem: str,
) -> Path | None:
    """Normalize and concatenate clips into one montage. None if no clips."""
    if not clips:
        return None
    w = config.get(f"video.{video_format}.width", 1080 if video_format == "short" else 1920)
    h = config.get(f"video.{video_format}.height", 1920 if video_format == "short" else 1080)
    fps = config.get(f"video.{video_format}.fps", 30)
    seg_dur = float(config.get("generate.segment_sec", 5))

    seg_dir = config.workdir / "montage" / stem
    seg_dir.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    for i, clip in enumerate(clips):
        seg = seg_dir / f"seg{i:02d}.mp4"
        try:
            _normalize_segment(clip, seg, w=w, h=h, fps=fps, seconds=seg_dur)
            segments.append(seg)
        except Exception as e:
            log(f"Skipping clip {clip.name}: {e}", level="warn")

    if not segments:
        return None
    if len(segments) == 1:
        return segments[0]

    # Concat demuxer — safe because all segments share codec/res/fps.
    list_file = seg_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{s.as_posix()}'\n" for s in segments), encoding="utf-8"
    )
    montage = seg_dir / "montage.mp4"
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        str(montage),
    ])
    log(f"Built montage from {len(segments)} clips: {montage.name}", level="ok")
    return montage


def _normalize_segment(
    src: Path, out: Path, *, w: int, h: int, fps: int, seconds: float
) -> None:
    run([
        "ffmpeg", "-y",
        "-t", f"{seconds:.2f}", "-i", str(src),
        "-vf",
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,fps={fps}",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(out),
    ])
