"""Lightweight job tracking.

Every produced video gets a job record (JSON) under <workdir>/jobs/. This lets
`upload --latest` find the most recent render and lets you audit what was made
and whether it's been uploaded yet.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .utils import timestamp_slug


@dataclass
class Job:
    id: str
    mode: str                       # "generate" | "clip"
    video_format: str               # "short" | "long"
    video_path: str                 # rendered file
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""                # source video (clip mode)
    topic: str = ""                 # topic (generate mode)
    uploaded: bool = False
    youtube_id: str = ""
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    def __init__(self, workdir: Path):
        self.dir = workdir / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def new_id(self, mode: str) -> str:
        return f"{timestamp_slug()}-{mode}"

    def save(self, job: Job) -> Path:
        if not job.created_at:
            job.created_at = timestamp_slug()
        path = self._path(job.id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job.to_dict(), f, indent=2)
        return path

    def load(self, job_id: str) -> Job:
        with open(self._path(job_id), "r", encoding="utf-8") as f:
            return Job(**json.load(f))

    def all(self) -> list[Job]:
        jobs = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    jobs.append(Job(**json.load(f)))
            except Exception:
                continue
        return jobs

    def latest(self, *, not_uploaded: bool = False) -> Job | None:
        jobs = self.all()
        if not_uploaded:
            jobs = [j for j in jobs if not j.uploaded]
        return jobs[-1] if jobs else None
