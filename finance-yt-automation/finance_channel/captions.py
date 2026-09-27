"""Captions: short, punchy chunks from word timings, burned in as ASS subtitles.

ASS (not SRT) is used so the subtitle canvas matches the real video size.
With SRT, libass assumes a 384x288 landscape canvas, which makes captions far
too large on vertical Shorts and pushes them over the on-screen numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config


def chunk_words(words: list[dict[str, Any]], words_per_caption: int = 4) -> list[tuple[float, float, str]]:
    """Group words into small chunks; break early after sentence punctuation."""
    chunks: list[tuple[float, float, str]] = []
    buf: list[dict[str, Any]] = []
    for w in words:
        buf.append(w)
        token = str(w["word"]).strip()
        if len(buf) >= words_per_caption or token.endswith((".", "!", "?", ":", ";")):
            chunks.append((buf[0]["start"], buf[-1]["end"], " ".join(str(x["word"]).strip() for x in buf)))
            buf = []
    if buf:
        chunks.append((buf[0]["start"], buf[-1]["end"], " ".join(str(x["word"]).strip() for x in buf)))
    # Hold each caption until the next begins (no flicker between chunks).
    return [(s, max(e, chunks[i + 1][0]) if i + 1 < len(chunks) else e, t)
            for i, (s, e, t) in enumerate(chunks)]


def _ass_ts(seconds: float) -> str:
    cs_total = int(round(max(0.0, seconds) * 100))
    h, rem = divmod(cs_total, 360_000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(
    words: list[dict[str, Any]], out_path: Path, *, config: Config, width: int, height: int,
    position: str | None = None,
) -> Path:
    """Write an ASS subtitle file sized for a width x height video."""
    portrait = height > width
    base = float(config.get("captions.font_size", 18))
    # font_size 18 -> ~86px on 1080x1920, ~59px on 1920x1080.
    size = int(round(base * height / (400 if portrait else 330)))
    pos = position or config.get("captions.position", "center")
    alignment = 2 if pos == "bottom" else 5          # ASS numpad: 2 bottom-center, 5 middle
    margin_v = int(height * (0.13 if portrait else 0.07)) if pos == "bottom" else 0
    margin_lr = int(width * 0.07)
    font = config.get("captions.font", "Arial")
    primary = config.get("captions.primary_color", "&H00FFFFFF")
    outline_c = config.get("captions.outline_color", "&H00000000")
    outline = max(2, size // 14)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},{primary},{primary},{outline_c},&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{max(1, outline // 2)},{alignment},{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(e)},Caption,,0,0,0,,{{\\fad(60,0)}}{_escape(t)}"
        for s, e, t in chunk_words(words, int(config.get("captions.words_per_caption", 4)))
        if t
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_path


def subtitles_filter(ass_path: Path) -> str:
    """ffmpeg filter that burns in an ASS file."""
    path = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    return f"subtitles='{path}'"
