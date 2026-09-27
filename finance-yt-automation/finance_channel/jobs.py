"""Lightweight job tracking.

Every produced video gets a job record (JSON) under <workdir>/jobs/. This lets
`upload --latest` find the most recent render and lets you audit what was made,
what the compliance review said, and whether it has been uploaded.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .utils import timestamp_slug


@dataclass
class Job:
    id: str
    video_format: str               # "short" | "long"
    video_path: str
    topic: str = ""
    pillar: str = ""
    plan_path: str = ""
    thumbnail_path: str = ""
    title: str = ""
    description: str = ""           # final description incl. disclaimers
    tags: list[str] = field(default_factory=list)
    fact_check: list[str] = field(default_factory=list)   # claims a human must verify
    review_status: str = ""         # "approved" | "approved_with_warnings" | "blocked"
    uploaded: bool = False
    youtube_id: str = ""
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class JobStore:
    def __init__(self, workdir: Path):
        self.dir = workdir / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def new_id(self, suffix: str = "video") -> str:
        base = f"{timestamp_slug()}-{suffix}"
        job_id, n = base, 2
        while self._path(job_id).exists():
            job_id = f"{base}-{n}"
            n += 1
        return job_id

    def save(self, job: Job) -> Path:
        if not job.created_at:
            job.created_at = timestamp_slug()
        path = self._path(job.id)
        path.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, job_id: str) -> Job:
        return Job.from_dict(json.loads(self._path(job_id).read_text(encoding="utf-8")))

    def all(self) -> list[Job]:
        jobs = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                jobs.append(Job.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return jobs

    def latest(self, *, not_uploaded: bool = False) -> Job | None:
        jobs = self.all()
        if not_uploaded:
            jobs = [j for j in jobs if not j.uploaded and j.review_status != "blocked"]
        return jobs[-1] if jobs else None
