"""Transcription via faster-whisper (local, free).

Returns word-ish segments with start/end timestamps, used both for highlight
detection (clip mode) and for caption generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import log


def transcribe(video_path: Path, *, workdir: Path, model_size: str = "base") -> list[dict[str, Any]]:
    """Transcribe a media file. Results are cached next to the source.

    model_size: tiny | base | small | medium | large-v3 (bigger = slower/better)
    """
    cache = workdir / "transcripts" / f"{video_path.stem}.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        log(f"Using cached transcript: {cache.name}", level="ok")
        with open(cache, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper not installed. `pip install faster-whisper`."
        ) from e

    log(f"Transcribing {video_path.name} with Whisper ({model_size})...", level="step")
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, info = model.transcribe(str(video_path), vad_filter=True, word_timestamps=True)

    out: list[dict[str, Any]] = []
    for seg in segments:
        words = [
            {"start": w.start, "end": w.end, "word": w.word}
            for w in (seg.words or [])
        ]
        out.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": words,
            }
        )

    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    log(f"Transcribed {len(out)} segments ({info.language}).", level="ok")
    return out
