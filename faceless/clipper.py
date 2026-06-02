"""ffmpeg-based clipping and reframing.

Cuts a time range out of a source video, reframes it to the target aspect ratio
(9:16 for Shorts, 16:9 for long-form), and optionally burns in captions.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .utils import require_ffmpeg, run


def _reframe_filter(config: Config, video_format: str) -> str:
    """Build the scale/crop filter that maps the source to the target frame."""
    if video_format == "short":
        w = config.get("video.short.width", 1080)
        h = config.get("video.short.height", 1920)
        strategy = config.get("clip.reframe", "blurred_padding")
        if strategy == "center_crop":
            return f"crop=ih*{w}/{h}:ih,scale={w}:{h}[vid]"
        # blurred_padding: blurred fill behind the fitted foreground.
        return (
            f"split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20[bg];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vid]"
        )
    # long-form: fit to 16:9 with letterbox if needed.
    w = config.get("video.long.width", 1920)
    h = config.get("video.long.height", 1080)
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[vid]"
    )


def cut_clip(
    source: Path,
    out_path: Path,
    *,
    start: float,
    end: float,
    config: Config,
    video_format: str,
    subtitles_filter: str | None = None,
) -> Path:
    """Cut [start, end] from source, reframe, optionally caption, and encode."""
    require_ffmpeg()
    fps = config.get(f"video.{video_format}.fps", 30)
    duration = max(0.5, end - start)

    reframe = _reframe_filter(config, video_format)
    # The reframe graph labels its output [vid]. To add captions, rename that
    # sink to [pre] and feed it through the subtitles filter into a new [vid].
    if subtitles_filter:
        reframe = reframe.replace("[vid]", "[pre]", 1)
        filter_complex = f"[0:v]{reframe};[pre]{subtitles_filter}[vid]"
    else:
        filter_complex = f"[0:v]{reframe}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vid]",
        "-map",
        "0:a?",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    run(cmd)
    return out_path
