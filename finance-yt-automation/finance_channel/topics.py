"""Topic queue for batch / scheduled production.

Reads topics from a plain-text file, one per line. `#` starts a comment. A line
may be tagged with a content pillar using `pillar | topic`. Produced topics are
tracked in <workdir>/topics_state.json so reruns never redo a topic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


def _key(topic: str) -> str:
    return hashlib.sha256(topic.strip().lower().encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Topic:
    text: str
    pillar: str = ""

    @classmethod
    def parse(cls, line: str) -> "Topic":
        if "|" in line:
            pillar, _, text = line.partition("|")
            return cls(text=text.strip(), pillar=pillar.strip())
        return cls(text=line.strip())

    def to_line(self) -> str:
        return f"{self.pillar} | {self.text}" if self.pillar else self.text


class TopicQueue:
    def __init__(self, topics_file: str | Path, workdir: Path):
        self.topics_file = Path(topics_file)
        self.state_path = Path(workdir) / "topics_state.json"
        self._done: set[str] = set()
        if self.state_path.exists():
            try:
                self._done = set(json.loads(self.state_path.read_text("utf-8")).get("done", []))
            except Exception:
                self._done = set()

    def all_topics(self) -> list[Topic]:
        if not self.topics_file.exists():
            raise FileNotFoundError(
                f"Topics file not found: {self.topics_file}. "
                "Copy topics.example.txt to topics.txt, or run `python pipeline.py ideas --append`."
            )
        topics = []
        for line in self.topics_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                t = Topic.parse(line)
                if t.text:
                    topics.append(t)
        return topics

    def pending(self, limit: int | None = None) -> list[Topic]:
        """Topics not yet produced, in file order."""
        out = [t for t in self.all_topics() if _key(t.text) not in self._done]
        return out[:limit] if limit else out

    def remaining_count(self) -> int:
        return len(self.pending())

    def mark_done(self, topic: Topic | str) -> None:
        text = topic.text if isinstance(topic, Topic) else topic
        self._done.add(_key(text))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"done": sorted(self._done)}, indent=2), "utf-8")

    def append(self, topics: list[Topic]) -> list[Topic]:
        """Append new topics to the file, skipping duplicates. Returns what was added."""
        existing = set()
        if self.topics_file.exists():
            existing = {_key(t.text) for t in self.all_topics()}
        added = []
        for t in topics:
            k = _key(t.text)
            if t.text and k not in existing and k not in self._done:
                added.append(t)
                existing.add(k)
        if added:
            self.topics_file.parent.mkdir(parents=True, exist_ok=True)
            prefix = ""
            if self.topics_file.exists():
                text = self.topics_file.read_text(encoding="utf-8")
                if text and not text.endswith("\n"):
                    prefix = "\n"
            with open(self.topics_file, "a", encoding="utf-8") as f:
                f.write(prefix + "".join(t.to_line() + "\n" for t in added))
        return added
