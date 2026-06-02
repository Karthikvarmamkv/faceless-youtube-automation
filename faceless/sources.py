"""Source acquisition: local ingest, downloading, and the rights gate.

The rights gate is the single most important guardrail in this project. We do
NOT process a source video for re-upload unless the operator has affirmed they
have the rights to it. See docs/RESPONSIBLE_USE.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import requests

from .config import Config, env
from .utils import log, run, slugify, timestamp_slug, which


class RightsError(RuntimeError):
    """Raised when a source is used without a rights affirmation."""


def confirm_rights(*, i_own_rights: bool, source_desc: str) -> None:
    """Enforce the rights gate.

    Pass i_own_rights=True only when the operator has confirmed (via the
    --i-own-rights flag or an interactive prompt) that they own or are licensed
    to use the source, or it is royalty-free / Creative Commons with attribution.
    """
    if i_own_rights:
        log(f"Rights affirmed for source: {source_desc}", level="ok")
        return
    raise RightsError(
        f"Refusing to process '{source_desc}' without a rights confirmation.\n"
        "Only use content you own, have licensed, or that is royalty-free / "
        "Creative Commons (with attribution). Re-run with --i-own-rights once "
        "you've confirmed you have the rights. See docs/RESPONSIBLE_USE.md."
    )


def ingest_local(path: str | Path, workdir: Path) -> Path:
    """Copy a local source video into the workdir's sources/ folder."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    sources_dir = workdir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    dest = sources_dir / f"{timestamp_slug()}-{slugify(src.stem)}{src.suffix}"
    shutil.copy2(src, dest)
    log(f"Ingested local source -> {dest.name}", level="ok")
    return dest


def download_url(url: str, workdir: Path) -> Path:
    """Download a source via yt-dlp (for content YOU own or CC-licensed sources)."""
    if not which("yt-dlp"):
        raise RuntimeError("yt-dlp not installed. `pip install yt-dlp`.")
    sources_dir = workdir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(sources_dir / f"{timestamp_slug()}-%(title).50s.%(ext)s")
    run(
        [
            "yt-dlp",
            "-f",
            "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "--merge-output-format",
            "mp4",
            "-o",
            out_tmpl,
            url,
        ]
    )
    # Find the newest mp4 in sources/.
    files = sorted(sources_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise RuntimeError("Download finished but no mp4 found.")
    log(f"Downloaded source -> {files[-1].name}", level="ok")
    return files[-1]


# --- Stock footage (generate mode) ----------------------------------------

def fetch_stock_clips(
    keywords: list[str], *, config: Config, count: int, orientation: str,
) -> list[Path]:
    """Fetch royalty-free background clips for keywords. Returns local file paths.

    Uses Pexels or Pixabay depending on config.generate.footage_source. Returns
    an empty list if no API key is configured (caller should fall back to a solid
    color background).
    """
    source = config.get("generate.footage_source", "pexels")
    workdir = config.workdir / "footage"
    workdir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for kw in keywords:
        if len(paths) >= count:
            break
        try:
            if source == "pexels":
                url = _pexels_video(kw, orientation)
            elif source == "pixabay":
                url = _pixabay_video(kw)
            else:
                url = None
        except Exception as e:  # network/API hiccup shouldn't kill the run
            log(f"Footage lookup failed for '{kw}': {e}", level="warn")
            url = None
        if not url:
            continue
        dest = workdir / f"{timestamp_slug()}-{slugify(kw)}.mp4"
        try:
            _download_file(url, dest)
            paths.append(dest)
        except Exception as e:
            log(f"Footage download failed for '{kw}': {e}", level="warn")

    if not paths:
        log("No stock footage fetched (missing API key or no matches).", level="warn")
    return paths


def _pexels_video(query: str, orientation: str) -> str | None:
    key = env("PEXELS_API_KEY")
    if not key:
        return None
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": query, "per_page": 1, "orientation": orientation},
        timeout=30,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        return None
    files = sorted(
        videos[0]["video_files"],
        key=lambda f: (f.get("height") or 0),
        reverse=True,
    )
    return files[0]["link"] if files else None


def _pixabay_video(query: str) -> str | None:
    key = env("PIXABAY_API_KEY")
    if not key:
        return None
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": query, "per_page": 3},
        timeout=30,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        return None
    return hits[0]["videos"]["large"]["url"]


def _download_file(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
