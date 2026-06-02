"""Topic queue for batch / scheduled production.

Reads topics from a plain-text file (one topic per line, `#` for comments) and
tracks which have already been produced via a small JSON state file in the
workdir — so batch and scheduled runs are idempotent and won't redo a topic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _key(topic: str) -> str:
    return hashlib.sha256(topic.strip().lower().encode("utf-8")).hexdigest()[:16]


class TopicQueue:
    def __init__(self, topics_file: Path, workdir: Path):
        self.topics_file = Path(topics_file)
        self.state_path = workdir / "topics_state.json"
        self._done: set[str] = set()
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    self._done = set(json.load(f).get("done", []))
            except Exception:
                self._done = set()

    def _all_topics(self) -> list[str]:
        if not self.topics_file.exists():
            raise FileNotFoundError(
                f"Topics file not found: {self.topics_file}. "
                "Copy topics.example.txt to topics.txt and add your ideas."
            )
        topics = []
        for line in self.topics_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                topics.append(line)
        return topics

    def pending(self, limit: int | None = None) -> list[str]:
        """Topics not yet produced, in file order."""
        out = [t for t in self._all_topics() if _key(t) not in self._done]
        return out[:limit] if limit else out

    def remaining_count(self) -> int:
        return len(self.pending())

    def mark_done(self, topic: str) -> None:
        self._done.add(_key(topic))
        self._save()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump({"done": sorted(self._done)}, f, indent=2)
