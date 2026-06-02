"""Caption generation: build SRT from transcript segments and burn it in.

We produce short, readable caption chunks (a few words at a time) for that
fast-paced faceless look, and return an ffmpeg `subtitles` filter string with
libass force_style so the captions are styled consistently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config


def _fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(
    segments: list[dict[str, Any]],
    out_path: Path,
    *,
    offset: float = 0.0,
    words_per_caption: int = 4,
) -> Path:
    """Build an SRT, grouping words into small caption chunks.

    offset shifts all timestamps (use the clip start when captioning a sub-clip
    so timings begin at 0).
    """
    chunks: list[tuple[float, float, str]] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            # No word timing — fall back to the whole segment.
            chunks.append((seg["start"], seg["end"], seg["text"].strip()))
            continue
        buf: list[dict[str, Any]] = []
        for w in words:
            buf.append(w)
            if len(buf) >= words_per_caption:
                chunks.append(
                    (buf[0]["start"], buf[-1]["end"], "".join(x["word"] for x in buf).strip())
                )
                buf = []
        if buf:
            chunks.append(
                (buf[0]["start"], buf[-1]["end"], "".join(x["word"] for x in buf).strip())
            )

    lines = []
    idx = 1
    for start, end, text in chunks:
        s = start - offset
        e = end - offset
        if e <= 0:
            continue
        s = max(s, 0)
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_fmt_ts(s)} --> {_fmt_ts(e)}")
        lines.append(text)
        lines.append("")
        idx += 1

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def subtitles_filter(srt_path: Path, config: Config, video_format: str) -> str:
    """Return an ffmpeg filter string that burns the SRT in with styling."""
    base = config.get("captions.font_size", 18)
    # Scale font with format (vertical needs bigger relative text).
    font_size = int(base * (1.6 if video_format == "short" else 1.2))
    font = config.get("captions.font", "Arial")
    primary = config.get("captions.primary_color", "&H00FFFFFF")
    outline = config.get("captions.outline_color", "&H00000000")
    alignment = 2 if config.get("captions.position", "center") == "bottom" else 10

    style = (
        f"FontName={font},FontSize={font_size},"
        f"PrimaryColour={primary},OutlineColour={outline},"
        f"BorderStyle=1,Outline=2,Shadow=0,Alignment={alignment},MarginV=60"
    )
    # Escape path for ffmpeg filter (colons/backslashes on Windows).
    path = str(srt_path).replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{path}':force_style='{style}'"
