"""Background footage for narration scenes.

Sources (config `visuals.footage_source`):
  pexels / pixabay  free stock video (needs an API key)
  higgsfield        AI-generated B-roll via any configured Higgsfield model
                    (costs credits; capped by visuals.higgsfield_max_clips)
  none              gradient background only
"""

from __future__ import annotations

from pathlib import Path

import requests

from .config import Config, env
from .utils import log, slugify


def fetch_clip(query: str, *, config: Config, orientation: str, dest_dir: Path,
               allow_paid: bool = True) -> Path | None:
    """Return a local clip for `query`, or None (caller falls back to a gradient)."""
    source = config.get("visuals.footage_source", "pexels")
    style = config.get("visuals.footage_style", "")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slugify(query)}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    try:
        if source == "higgsfield":
            if not allow_paid:
                return None
            return _higgsfield(query, style, config=config, orientation=orientation, dest=dest)
        search = f"{query} {style}".strip() if source != "pexels" else query
        url = None
        if source == "pexels":
            url = _pexels(search, orientation)
        elif source == "pixabay":
            url = _pixabay(search)
        if not url:
            return None
        _download(url, dest)
        return dest
    except Exception as e:  # footage must never kill a render
        log(f"Footage for '{query}' unavailable: {e}", level="warn")
        return None


def _higgsfield(query: str, style: str, *, config: Config, orientation: str, dest: Path) -> Path | None:
    from . import higgsfield as hf

    model = config.get("visuals.higgsfield_model", "broll_video")
    prompt = (f"{query}. {style}. Stock-footage style B-roll, no text, no logos, "
              "no people's faces in close-up, smooth camera motion.")
    result = hf.generate(
        config, model,
        {"prompt": prompt, "aspect_ratio": "9:16" if orientation == "portrait" else "16:9"},
        purpose=f"b-roll: {query}",
    )
    return hf.download(result.urls[0], dest)


def _pexels(query: str, orientation: str) -> str | None:
    key = env("PEXELS_API_KEY")
    if not key:
        return None
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": query, "per_page": 3, "orientation": orientation, "size": "medium"},
        timeout=30,
    )
    r.raise_for_status()
    for video in r.json().get("videos", []):
        files = [f for f in video.get("video_files", []) if (f.get("height") or 0) <= 1920]
        files.sort(key=lambda f: f.get("height") or 0, reverse=True)
        if files:
            return files[0]["link"]
    return None


def _pixabay(query: str) -> str | None:
    key = env("PIXABAY_API_KEY")
    if not key:
        return None
    r = requests.get("https://pixabay.com/api/videos/",
                     params={"key": key, "q": query, "per_page": 3}, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    return hits[0]["videos"]["large"]["url"] if hits else None


def _download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
