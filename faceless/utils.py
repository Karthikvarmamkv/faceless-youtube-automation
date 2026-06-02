"""Shared helpers: logging, shell, ffmpeg/ffprobe wrappers."""

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


def run(cmd: list[str], *, quiet: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess, raising with captured stderr on failure."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd[:4])} ...\n{tail}"
        )
    if not quiet and result.stderr:
        log(result.stderr.strip(), level="info")
    return result


def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds."""
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def slugify(text: str, max_len: int = 50) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    slug = "-".join(keep.lower().split())
    return slug[:max_len].strip("-") or "untitled"
