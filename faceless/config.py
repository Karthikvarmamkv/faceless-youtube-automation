"""Configuration and secrets loading.

Config comes from `config.yaml` (falls back to `config.example.yaml` so the
project runs out of the box). Secrets come from environment variables, loaded
from `.env` if present.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at import time
    pass

ROOT = Path(__file__).resolve().parent.parent


class Config:
    """Thin wrapper around the parsed YAML with dotted-path access."""

    def __init__(self, data: dict[str, Any], path: Path):
        self._data = data
        self.path = path

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        if path is not None:
            cfg_path = Path(path)
        else:
            cfg_path = ROOT / "config.yaml"
            if not cfg_path.exists():
                cfg_path = ROOT / "config.example.yaml"
        if not cfg_path.exists():
            raise FileNotFoundError(
                f"No config found at {cfg_path}. Copy config.example.yaml to config.yaml."
            )
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(data, cfg_path)

    def get(self, dotted: str, default: Any = None) -> Any:
        """Fetch a nested value, e.g. config.get('video.short.width')."""
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    @property
    def workdir(self) -> Path:
        wd = ROOT / self.get("workdir", "data")
        wd.mkdir(parents=True, exist_ok=True)
        return wd


# --- Secrets ---------------------------------------------------------------

def env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else val


def require_env(name: str) -> str:
    val = env(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Set it in your .env (see .env.example)."
        )
    return val
