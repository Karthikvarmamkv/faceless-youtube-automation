"""Shared helpers: logging, shell, ffmpeg/ffprobe wrappers, formatting."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def log(msg: str, *, level: str = "info") -> None:
    prefix = {
        "info": "•",
        "ok": "✓",
        "warn": "!",
        "error": "✗",
        "step": "▶",
    }.get(level, "•")
    print(f"{prefix} {msg}", file=sys.stderr, flush=True)


def which(binary: str) -> str | None:
    return shutil.which(binary)


def require_ffmpeg() -> None:
    if not which("ffmpeg") or not which("ffprobe"):
        raise RuntimeError(
            "ffmpeg/ffprobe not found on PATH. Install ffmpeg first:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows: https://www.gyan.dev/ffmpeg/builds/"
        )


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a subprocess, raising with captured stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd[:4])} ...\n{tail}"
        )
    return result


def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds."""
    out = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]).stdout
    return float(json.loads(out)["format"]["duration"])


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def slugify(text: str, max_len: int = 50) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    slug = "-".join(keep.lower().split())
    return slug[:max_len].strip("-") or "untitled"


def money(value: float, symbol: str = "$", decimals: int = 0) -> str:
    """Format a number as currency: money(243994.3) -> '$243,994'."""
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.{decimals}f}"


def compact_money(value: float, symbol: str = "$") -> str:
    """Short currency for chart axes: 1_250_000 -> '$1.25M', 72_000 -> '$72K'."""
    v = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_000_000:
        return f"{sign}{symbol}{v / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if v >= 10_000:
        return f"{sign}{symbol}{v / 1_000:.0f}K"
    if v >= 1_000:
        return f"{sign}{symbol}{v / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{sign}{symbol}{v:,.0f}"


def fmt_clock(seconds: float) -> str:
    """Chapter timestamp: 75 -> '1:15', 3725 -> '1:02:05'."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
