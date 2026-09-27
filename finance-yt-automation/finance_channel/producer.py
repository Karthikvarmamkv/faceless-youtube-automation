"""End-to-end production: plan -> verify numbers -> review -> render -> package."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import charts, compliance
from .config import Config
from .jobs import Job, JobStore
from .schemas import ScriptReview, VideoMetadata, VideoPlan
from .utils import fmt_clock, log, slugify, timestamp_slug


class ComplianceBlocked(RuntimeError):
    """The script still has a critical compliance problem after review."""


@dataclass
class ReviewedPlan:
    topic: str
    pillar: str
    video_format: str
    plan: VideoPlan
    computed_facts: list[str]
    review: ScriptReview | None
    scanner_findings: list[dict] = field(default_factory=list)
    status: str = "approved"             # approved | approved_with_warnings | blocked

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "topic": self.topic, "pillar": self.pillar, "video_format": self.video_format,
            "status": self.status, "computed_facts": self.computed_facts,
            "scanner_findings": self.scanner_findings,
            "review": self.review.model_dump() if self.review else None,
            "plan": self.plan.model_dump(),
        }, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "ReviewedPlan":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            topic=d["topic"], pillar=d.get("pillar", ""), video_format=d["video_format"],
            plan=VideoPlan.model_validate(d["plan"]), computed_facts=d.get("computed_facts", []),
            review=ScriptReview.model_validate(d["review"]) if d.get("review") else None,
            scanner_findings=d.get("scanner_findings", []), status=d.get("status", "approved"),
        )


def compute_facts(plan: VideoPlan, symbol: str) -> tuple[list[str], list[str]]:
    """(facts, problems): computed chart numbers, and scenes whose charts are invalid."""
    facts, problems = [], []
    for i, s in enumerate(plan.scenes):
        if s.kind == "chart":
            if not s.chart:
                problems.append(f"scene {i}: chart scene without chart spec")
                continue
            try:
                facts += [f"scene {i} {f}" for f in charts.compute_chart(s.chart, symbol).facts]
            except ValueError as e:
                problems.append(f"scene {i}: {e}")
        elif s.kind == "stat" and not s.stat:
            problems.append(f"scene {i}: stat scene without stat spec")
    return facts, problems


def _repair_scenes(plan: VideoPlan, problems: list[str]) -> None:
    """Downgrade broken chart/stat scenes to narration so the render can't fail."""
    bad = {int(p.split()[1].rstrip(":")) for p in problems}
    for i in bad:
        s = plan.scenes[i]
        s.kind, s.chart, s.stat = "narration", None, None
        s.footage_query = s.footage_query or "money finance abstract"


def _scan_plan(plan: VideoPlan) -> list[dict]:
    out = []
    for i, s in enumerate(plan.scenes):
        for f in compliance.scan(s.narration):
            out.append({"scene": i, "severity": f.severity, "rule": f.rule,
                        "excerpt": f.excerpt, "advice": f.advice})
    return out


def plan_and_review(topic: str, *, pillar: str, video_format: str, config: Config, llm) -> ReviewedPlan:
    symbol = config.get("channel.currency_symbol", "$")
    log(f"Planning {video_format} video: {topic}", level="step")
    plan = llm.plan_video(topic, video_format=video_format, pillar=pillar)
    log(f"Plan: '{plan.title_idea}' ({len(plan.scenes)} scenes)", level="ok")

    facts, problems = compute_facts(plan, symbol)
    if problems:
        for p in problems:
            log(f"Invalid visual, using footage instead: {p}", level="warn")
        _repair_scenes(plan, problems)
        facts, _ = compute_facts(plan, symbol)

    findings = _scan_plan(plan)
    review = None
    if config.get("llm.review_scripts", True):
        log("Fact-checking and compliance-reviewing the script...", level="step")
        review = llm.review_script(
            plan, computed_facts=facts,
            scanner_findings=[f"scene {f['scene']} [{f['severity']}] {f['rule']}: {f['excerpt']}"
                              for f in findings],
        )
        if len(review.revised_narrations) == len(plan.scenes):
            for s, text in zip(plan.scenes, review.revised_narrations):
                if text.strip():
                    s.narration = text.strip()
        else:
            log("Reviewer returned the wrong number of scenes; keeping the original narration.",
                level="warn")
        for issue in review.issues:
            lvl = "warn" if issue.severity != "info" else "info"
            log(f"review [{issue.severity}] scene {issue.scene_index}: {issue.problem}", level=lvl)

    # Spoken disclaimer on the last scene.
    disclaimer = (config.get("compliance.spoken_disclaimer") or "").strip()
    if disclaimer and plan.scenes and disclaimer not in plan.scenes[-1].narration:
        plan.scenes[-1].narration = f"{plan.scenes[-1].narration.rstrip()} {disclaimer}"

    findings = _scan_plan(plan)   # re-scan the final text
    critical = [f for f in findings if f["severity"] == "critical"]
    unresolved_llm = [i for i in (review.issues if review else []) if i.severity == "critical"]
    if critical:
        status = "blocked" if config.get("compliance.block_on_violation", True) else "approved_with_warnings"
    elif findings or (review and any(i.severity == "warning" for i in review.issues)) or unresolved_llm:
        status = "approved_with_warnings"
    else:
        status = "approved"
    return ReviewedPlan(topic=topic, pillar=pillar, video_format=video_format, plan=plan,
                        computed_facts=facts, review=review, scanner_findings=findings, status=status)


def build_description(meta: VideoMetadata, config: Config, chapters: list[tuple[float, str]]) -> str:
    parts = [meta.description.strip()]
    if chapters:
        parts.append("Chapters:\n" + "\n".join(f"{fmt_clock(t)} {label}" for t, label in chapters))
    for key in ("compliance.description_disclaimer", "compliance.affiliate_disclosure",
                "compliance.ai_disclosure"):
        text = (config.get(key) or "").strip()
        if text:
            parts.append(" ".join(text.split()))
    if meta.hashtags:
        parts.append(" ".join(h if h.startswith("#") else f"#{h}" for h in meta.hashtags))
    return "\n\n".join(parts)


def produce(reviewed: ReviewedPlan, *, config: Config, store: JobStore, llm,
            allow_silent_fallback: bool = False) -> Job:
    """Render a reviewed plan and save a job ready for upload review."""
    from .render import build_chapters, render_plan

    if reviewed.status == "blocked":
        crit = [f for f in reviewed.scanner_findings if f["severity"] == "critical"]
        raise ComplianceBlocked(
            "Script blocked by compliance check: "
            + "; ".join(f"scene {f['scene']} {f['rule']}: {f['excerpt']}" for f in crit)
        )
    plan = reviewed.plan
    stem = f"{timestamp_slug()}-{slugify(plan.title_idea, 40)}"
    result = render_plan(plan, config=config, video_format=reviewed.video_format, stem=stem,
                         allow_silent_fallback=allow_silent_fallback)

    thumb = config.workdir / "thumbnails" / f"{stem}.png"
    charts.render_thumbnail(plan.thumbnail_text or plan.title_idea, thumb,
                            theme=config.get("visuals.chart_theme"))

    if llm is not None:
        log("Writing title, description, and tags...", level="step")
        meta = llm.write_metadata(plan, video_format=reviewed.video_format, topic=reviewed.topic)
    else:
        meta = VideoMetadata(title=plan.title_idea, description=plan.hook,
                             tags=["personal finance"], hashtags=["#personalfinance"])
    if reviewed.video_format == "short" and not any(h.lower() == "#shorts" for h in meta.hashtags):
        meta.hashtags.append("#shorts")
    chapters = build_chapters(result.scenes) if reviewed.video_format == "long" else []

    plan_path = config.workdir / "plans" / f"{stem}.json"
    reviewed.save(plan_path)
    fact_check = list(dict.fromkeys(
        (reviewed.review.fact_check if reviewed.review else []) + plan.key_claims))
    job = Job(
        id=store.new_id(reviewed.video_format),
        video_format=reviewed.video_format,
        video_path=str(result.video_path),
        topic=reviewed.topic, pillar=reviewed.pillar,
        plan_path=str(plan_path), thumbnail_path=str(thumb),
        title=meta.title, description=build_description(meta, config, chapters),
        tags=meta.tags, fact_check=fact_check, review_status=reviewed.status,
        extra={"duration_sec": round(result.duration, 2), "hashtags": meta.hashtags,
               "chapters": [[round(t, 1), label] for t, label in chapters]},
    )
    store.save(job)
    log(f"Saved job {job.id}", level="ok")
    return job
