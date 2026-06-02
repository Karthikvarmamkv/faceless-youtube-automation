"""Voiceover generation via edge-tts (free Microsoft neural voices).

Produces an MP3 plus word-boundary timing, which we convert into the same
segment/word structure the transcription module emits — so captions work
identically for generated and clipped videos.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .config import Config
from .utils import log


def synthesize(text: str, out_path: Path, *, config: Config) -> tuple[Path, list[dict[str, Any]]]:
    """Generate voiceover audio and word-timed segments.

    Returns (audio_path, segments) where segments mirror transcribe.transcribe().
    """
    try:
        import edge_tts
    except ImportError as e:
        raise RuntimeError("edge-tts not installed. `pip install edge-tts`.") from e

    voice = config.get("voiceover.voice", "en-US-AndrewNeural")
    rate = config.get("voiceover.rate", "+0%")
    volume = config.get("voiceover.volume", "+0%")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Synthesizing voiceover ({voice})...", level="step")
    word_marks = asyncio.run(_run(text, out_path, voice, rate, volume))

    # Group words into ~1s pseudo-segments so captions chunk nicely.
    segments = _words_to_segments(word_marks)
    log(f"Voiceover ready: {out_path.name} ({len(word_marks)} words).", level="ok")
    return out_path, segments


async def _run(text, out_path, voice, rate, volume) -> list[dict[str, Any]]:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    words: list[dict[str, Any]] = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7  # 100ns ticks -> seconds
                dur = chunk["duration"] / 1e7
                words.append(
                    {"start": start, "end": start + dur, "word": " " + chunk["text"]}
                )
    return words


def _words_to_segments(words: list[dict[str, Any]], window: float = 3.0) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    buf: list[dict[str, Any]] = []
    seg_start = 0.0
    for w in words:
        if not buf:
            seg_start = w["start"]
        buf.append(w)
        if w["end"] - seg_start >= window:
            segments.append(_flush(buf))
            buf = []
    if buf:
        segments.append(_flush(buf))
    return segments


def _flush(buf: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "start": buf[0]["start"],
        "end": buf[-1]["end"],
        "text": "".join(w["word"] for w in buf).strip(),
        "words": buf,
    }
