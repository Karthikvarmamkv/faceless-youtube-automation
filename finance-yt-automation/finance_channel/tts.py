"""Voiceover via edge-tts (free Microsoft neural voices) with word timings.

Each scene is synthesized separately so its visuals can be cut to the exact
length of its narration.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from .config import Config
from .utils import log, run


def synthesize(
    text: str, out_path: Path, *, config: Config, allow_silent_fallback: bool = False,
) -> tuple[Path, list[dict[str, Any]]]:
    """Return (audio_path, words) where words = [{start, end, word}, ...] in seconds.

    With allow_silent_fallback=True (used by the offline demo), a TTS failure
    produces silent audio with evenly spaced word timings instead of raising.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    voice = config.get("voiceover.voice", "en-US-ChristopherNeural")
    rate = config.get("voiceover.rate", "+0%")
    volume = config.get("voiceover.volume", "+0%")
    try:
        import edge_tts  # noqa: F401

        words = asyncio.run(_edge(text, out_path, voice, rate, volume))
        if not words or out_path.stat().st_size == 0:
            raise RuntimeError("edge-tts returned no audio")
        return out_path, words
    except Exception as e:
        if not allow_silent_fallback:
            raise RuntimeError(f"Voiceover failed ({e}). Is edge-tts installed and online?") from e
        log(f"TTS unavailable ({type(e).__name__}); using silent placeholder audio.", level="warn")
        return _silent(text, out_path)


async def _edge(text: str, out_path: Path, voice: str, rate: str, volume: str) -> list[dict[str, Any]]:
    import edge_tts

    # edge-tts uses aiohttp, which ignores the usual proxy / CA environment
    # variables. Honour them so TTS works behind corporate proxies.
    extra: dict[str, Any] = {}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        extra["proxy"] = proxy
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if cafile and os.path.exists(cafile):
        import ssl

        import aiohttp

        extra["connector"] = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=cafile))

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume,
                                       boundary="WordBoundary", **extra)
    words: list[dict[str, Any]] = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7   # 100ns ticks -> seconds
                dur = chunk["duration"] / 1e7
                words.append({"start": start, "end": start + dur, "word": chunk["text"]})
    return words


def _silent(text: str, out_path: Path, wps: float = 2.6) -> tuple[Path, list[dict[str, Any]]]:
    tokens = text.split()
    dur = max(1.5, len(tokens) / wps)
    out_path = out_path.with_suffix(".m4a")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{dur:.2f}", "-c:a", "aac", str(out_path)])
    step = dur / max(1, len(tokens))
    words = [{"start": i * step, "end": (i + 1) * step, "word": w} for i, w in enumerate(tokens)]
    return out_path, words
