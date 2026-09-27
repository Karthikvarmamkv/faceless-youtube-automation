#!/usr/bin/env python3
"""Finance faceless YouTube channel automation — CLI.

Content commands:
  doctor        Check dependencies, keys, and configuration
  ideas         Brainstorm new topics per content pillar (optionally append to topics.txt)
  plan          Write + fact-check + compliance-review a script (no rendering)
  render        Render a saved plan into a video
  make          plan + render in one go (optionally upload)
  batch         Produce videos from the topics file
  schedule      Run batch on a recurring interval (or once, for cron)
  upload        Upload a finished job to YouTube as a private draft
  jobs          List produced videos, review status, and fact-check items
  demo          Render a sample video offline (no API keys needed)

Higgsfield commands (AI video/image generation, credit-aware):
  hf-check      Show whether Higgsfield credentials are configured (never prints them)
  hf-models     List configured model presets and their credit prices
  hf-generate   Run one generation with any configured model or API id
  hf-usage      Summarise the local credit ledger

Run `python pipeline.py <command> -h` for options.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from finance_channel.config import ROOT, Config, env
from finance_channel.jobs import JobStore
from finance_channel.utils import log, which


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    config = Config.load(args.config)
    log(f"Config: {config.path}", level="info")
    ok = True
    for binary in ("ffmpeg", "ffprobe"):
        found = bool(which(binary))
        log(f"{binary}: {'found' if found else 'MISSING (install ffmpeg)'}",
            level="ok" if found else "error")
        ok &= found
    for mod, label in [("anthropic", "Anthropic SDK"), ("matplotlib", "matplotlib (charts)"),
                       ("edge_tts", "edge-tts (voiceover)"), ("googleapiclient", "Google API client (upload)"),
                       ("higgsfield_client", "higgsfield-client (optional AI video)")]:
        try:
            __import__(mod)
            log(f"{label}: installed", level="ok")
        except ImportError:
            log(f"{label}: not installed", level="warn")
    if env("ANTHROPIC_API_KEY"):
        log("ANTHROPIC_API_KEY: set", level="ok")
    else:
        log("ANTHROPIC_API_KEY: MISSING (required for plan/make/batch)", level="error")
        ok = False
    for key in ("PEXELS_API_KEY", "PIXABAY_API_KEY"):
        log(f"{key}: {'set' if env(key) else 'not set (optional)'}", level="ok" if env(key) else "info")
    from finance_channel.higgsfield import credential_status
    hf = credential_status()
    log(f"Higgsfield credentials: {hf}", level="ok" if hf.startswith("set") else "info")
    secret = ROOT / env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
    log(f"YouTube OAuth client: {'found' if secret.exists() else 'not found (needed for upload)'}",
        level="ok" if secret.exists() else "info")
    log("Doctor: OK" if ok else "Doctor: issues found (see above)", level="ok" if ok else "error")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# ideas / plan / render / make
# --------------------------------------------------------------------------

def cmd_ideas(args) -> int:
    from finance_channel.llm import LLM
    from finance_channel.topics import Topic, TopicQueue

    config = Config.load(args.config)
    queue = TopicQueue(args.topics, config.workdir)
    try:
        avoid = [t.text for t in queue.all_topics()]
    except FileNotFoundError:
        avoid = []
    ideas = LLM(config).brainstorm_ideas(count=args.count, pillar=args.pillar, avoid=avoid).ideas
    for idea in ideas:
        print(f"[{idea.pillar}] {idea.topic}\n    {idea.angle}")
    if args.append:
        added = queue.append([Topic(text=i.topic, pillar=i.pillar) for i in ideas])
        log(f"Appended {len(added)} new topic(s) to {queue.topics_file}", level="ok")
    return 0


def cmd_plan(args) -> int:
    from finance_channel.llm import LLM
    from finance_channel.producer import plan_and_review
    from finance_channel.utils import slugify, timestamp_slug

    config = Config.load(args.config)
    reviewed = plan_and_review(args.topic, pillar=args.pillar or "", video_format=args.format,
                               config=config, llm=LLM(config))
    path = Path(args.out) if args.out else (
        config.workdir / "plans" / f"{timestamp_slug()}-{slugify(reviewed.plan.title_idea, 40)}.json")
    reviewed.save(path)
    _print_plan(reviewed)
    log(f"Plan saved: {path}", level="ok")
    log(f"Render it with: python pipeline.py render --plan {path}", level="info")
    return 0 if reviewed.status != "blocked" else 1


def cmd_render(args) -> int:
    from finance_channel.llm import LLM
    from finance_channel.producer import ReviewedPlan, produce

    config = Config.load(args.config)
    reviewed = ReviewedPlan.load(Path(args.plan))
    llm = LLM(config) if env("ANTHROPIC_API_KEY") else None
    job = produce(reviewed, config=config, store=JobStore(config.workdir), llm=llm)
    _print_job(job)
    return _maybe_upload(job, config, args.upload)


def _make_one(topic: str, pillar: str, video_format: str, config: Config, llm):
    from finance_channel.producer import plan_and_review, produce

    reviewed = plan_and_review(topic, pillar=pillar, video_format=video_format, config=config, llm=llm)
    return produce(reviewed, config=config, store=JobStore(config.workdir), llm=llm)


def cmd_make(args) -> int:
    from finance_channel.llm import LLM

    config = Config.load(args.config)
    job = _make_one(args.topic, args.pillar or "", args.format, config, LLM(config))
    _print_job(job)
    return _maybe_upload(job, config, args.upload)


def cmd_batch(args) -> int:
    from finance_channel.llm import LLM
    from finance_channel.producer import ComplianceBlocked
    from finance_channel.topics import TopicQueue

    config = Config.load(args.config)
    queue = TopicQueue(args.topics, config.workdir)
    pending = queue.pending(limit=args.limit)
    if not pending:
        log("No pending topics. Add some, or run `python pipeline.py ideas --append`.", level="info")
        return 0
    log(f"Producing {len(pending)} video(s) from {queue.topics_file}", level="step")
    llm = LLM(config)
    made = failed = 0
    for topic in pending:
        try:
            job = _make_one(topic.text, topic.pillar, args.format, config, llm)
            queue.mark_done(topic)
            made += 1
            if args.upload:
                _maybe_upload(job, config, True)
        except ComplianceBlocked as e:
            # Don't retry blocked topics forever; mark done and surface the reason.
            queue.mark_done(topic)
            failed += 1
            log(f"Blocked '{topic.text}': {e}", level="error")
        except Exception as e:
            failed += 1
            log(f"Failed on '{topic.text}': {e}", level="error")
            if args.stop_on_error:
                return 1
    log(f"Batch complete: {made} produced, {failed} failed, {queue.remaining_count()} left.", level="ok")
    return 0 if failed == 0 else 1


def cmd_schedule(args) -> int:
    interval = _parse_interval(args.interval)

    def tick() -> None:
        cmd_batch(argparse.Namespace(config=args.config, topics=args.topics, limit=args.per_run,
                                     format=args.format, upload=args.upload, stop_on_error=False))

    if args.once:
        tick()
        return 0
    log(f"Scheduler: {args.per_run} video(s) every {args.interval}. Ctrl-C to stop.", level="step")
    while True:
        tick()
        log(f"Sleeping {args.interval}...", level="info")
        time.sleep(interval)


def cmd_demo(args) -> int:
    from finance_channel.demo import demo_plan
    from finance_channel.producer import ReviewedPlan, compute_facts, produce

    config = Config.load(args.config)
    plan = demo_plan()
    if args.format == "long":
        for s in plan.scenes:
            s.footage_query = s.footage_query if s.kind == "narration" else ""
    facts, _ = compute_facts(plan, config.get("channel.currency_symbol", "$"))
    reviewed = ReviewedPlan(topic="demo", pillar="demo", video_format=args.format, plan=plan,
                            computed_facts=facts, review=None)
    job = produce(reviewed, config=config, store=JobStore(config.workdir), llm=None,
                  allow_silent_fallback=True)
    _print_job(job)
    return 0


# --------------------------------------------------------------------------
# upload / jobs
# --------------------------------------------------------------------------

def cmd_upload(args) -> int:
    config = Config.load(args.config)
    store = JobStore(config.workdir)
    job = store.load(args.job) if args.job else store.latest(not_uploaded=True)
    if not job:
        log("No un-uploaded jobs found.", level="error")
        return 1
    if job.uploaded:
        log(f"Job {job.id} already uploaded: https://youtu.be/{job.youtube_id}", level="warn")
        return 0
    return _maybe_upload(job, config, True)


def _maybe_upload(job, config: Config, upload: bool) -> int:
    if not upload:
        log("Review the video and fact-check list, then: python pipeline.py upload --job "
            f"{job.id}", level="info")
        return 0
    from finance_channel.youtube import upload as yt_upload

    job.youtube_id = yt_upload(job, config)
    job.uploaded = True
    JobStore(config.workdir).save(job)
    return 0


def cmd_jobs(args) -> int:
    config = Config.load(args.config)
    jobs = JobStore(config.workdir).all()
    if not jobs:
        log("No jobs yet.", level="info")
        return 0
    for j in jobs:
        up = f"uploaded https://youtu.be/{j.youtube_id}" if j.uploaded else "not uploaded"
        print(f"{j.id}  [{j.video_format}]  review={j.review_status or '-'}  {up}")
        print(f"    title: {j.title}")
        print(f"    file:  {j.video_path}")
        for claim in j.fact_check[:5]:
            print(f"    verify: {claim}")
    return 0


# --------------------------------------------------------------------------
# Higgsfield
# --------------------------------------------------------------------------

def cmd_hf_check(args) -> int:
    from finance_channel.higgsfield import credential_status

    state = credential_status()
    log(f"Higgsfield credentials: {state}", level="ok" if state.startswith("set") else "error")
    if not state.startswith("set"):
        log("Add HF_KEY=key-id:key-secret to .env.local in the project root. See docs/HIGGSFIELD.md.",
            level="info")
    return 0 if state.startswith("set") else 1


def cmd_hf_models(args) -> int:
    from finance_channel.higgsfield import model_presets

    config = Config.load(args.config)
    presets = model_presets(config)
    if not presets:
        log("No presets under higgsfield.models in config.yaml.", level="info")
        return 0
    for p in presets.values():
        if p.credits_per_request is not None:
            price = f"{p.credits_per_request:g} credits/request"
        elif p.credits_per_second is not None:
            price = f"{p.credits_per_second:g} credits/second"
        else:
            price = "price not set"
        print(f"{p.name:<16} {p.id}\n    output={p.output}  {price}  defaults={json.dumps(p.defaults)}")
        if p.notes:
            print(f"    {p.notes}")
    return 0


def cmd_hf_generate(args) -> int:
    from finance_channel import higgsfield as hf

    config = Config.load(args.config)
    preset = hf.resolve_model(config, args.model)
    arguments = {"prompt": args.prompt, "duration": args.duration, "resolution": args.resolution,
                 "aspect_ratio": args.aspect_ratio}
    for kv in args.arg or []:
        key, _, value = kv.partition("=")
        try:
            arguments[key] = json.loads(value)
        except json.JSONDecodeError:
            arguments[key] = value
    if isinstance(arguments["duration"], float) and arguments["duration"].is_integer():
        arguments["duration"] = int(arguments["duration"])
    merged = {**preset.defaults, **{k: v for k, v in arguments.items() if v is not None}}
    estimate = preset.estimate_credits(merged)
    shown = {k: v for k, v in merged.items() if k != "prompt"}
    log(f"Model: {preset.id}  args: {json.dumps(shown)}", level="info")
    log(f"Estimated cost: {f'{estimate:g} credits' if estimate is not None else 'unknown'}", level="info")
    if not args.yes:
        if not sys.stdin.isatty():
            log("This is a billable request. Re-run with --yes to confirm.", level="error")
            return 2
        if input("This spends Higgsfield credits. Continue? [y/N] ").strip().lower() != "y":
            log("Cancelled.", level="info")
            return 1
    try:
        result = hf.generate(config, args.model, arguments, purpose="cli")
    except hf.HiggsfieldError as e:
        log(str(e), level="error")
        return 1
    for url in result.urls:
        print(url)
    if args.download:
        dest = hf.download(result.urls[0], Path(args.download))
        log(f"Saved {dest}", level="ok")
    return 0


def cmd_hf_usage(args) -> int:
    from collections import defaultdict

    from finance_channel.higgsfield import Ledger

    config = Config.load(args.config)
    ledger = Ledger(config.workdir)
    entries = ledger.entries()
    if not entries:
        log("No Higgsfield requests recorded yet.", level="info")
        return 0
    final = {}
    for e in entries:   # last record per request wins
        final[e.get("request_id") or f"{e['ts']}-{e['model']}"] = e
    by_model = defaultdict(lambda: {"n": 0, "ok": 0, "credits": 0.0})
    for e in final.values():
        m = by_model[e["model_id"]]
        m["n"] += 1
        if e["status"] == "completed":
            m["ok"] += 1
            m["credits"] += float(e.get("estimated_credits") or 0)
    for model_id, m in by_model.items():
        print(f"{model_id}: {m['n']} request(s), {m['ok']} completed, ~{m['credits']:g} credits (estimated)")
    print(f"Today (UTC): ~{ledger.credits_today():g} credits (estimated)")
    log("Estimates come from prices in config.yaml; check exact usage in the Higgsfield console.",
        level="info")
    return 0


# --------------------------------------------------------------------------

def _parse_interval(text: str) -> int:
    text = str(text).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if text and text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(float(text))


def _print_plan(reviewed) -> None:
    print("\n" + "=" * 64)
    print(f"  {reviewed.plan.title_idea}   [{reviewed.status}]")
    print("=" * 64)
    for i, s in enumerate(reviewed.plan.scenes):
        visual = s.chart.title if s.chart else (s.stat.value if s.stat else s.footage_query)
        print(f"\n[{i}] {s.kind.upper()} · {s.section} · {visual}\n{s.narration}")
    if reviewed.computed_facts:
        print("\nComputed numbers:\n" + "\n".join(f"  - {f}" for f in reviewed.computed_facts))
    for f in reviewed.scanner_findings:
        print(f"\n! scene {f['scene']} [{f['severity']}] {f['rule']}: {f['excerpt']}\n  {f['advice']}")
    if reviewed.review and reviewed.review.fact_check:
        print("\nVerify before publishing:\n" + "\n".join(f"  - {c}" for c in reviewed.review.fact_check))
    print("=" * 64 + "\n")


def _print_job(job) -> None:
    print("\n" + "=" * 64)
    print(f"  {job.title}   [{job.review_status}]")
    print("=" * 64)
    print(job.description)
    if job.tags:
        print("\nTags: " + ", ".join(job.tags))
    if job.fact_check:
        print("\nVerify before publishing:\n" + "\n".join(f"  - {c}" for c in job.fact_check))
    print(f"\nVideo:     {job.video_path}\nThumbnail: {job.thumbnail_path}")
    print("=" * 64 + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="Path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check deps and config").set_defaults(func=cmd_doctor)

    i = sub.add_parser("ideas", help="Brainstorm topics")
    i.add_argument("--count", type=int, default=10)
    i.add_argument("--pillar", help="Limit to one content pillar")
    i.add_argument("--topics", default="topics.txt")
    i.add_argument("--append", action="store_true", help="Append new ideas to the topics file")
    i.set_defaults(func=cmd_ideas)

    for name, fn, helptext in [("plan", cmd_plan, "Script + review only"),
                               ("make", cmd_make, "Plan + render")]:
        c = sub.add_parser(name, help=helptext)
        c.add_argument("--topic", required=True)
        c.add_argument("--pillar", default="")
        c.add_argument("--format", choices=["short", "long"], default="short")
        if name == "plan":
            c.add_argument("--out", help="Where to save the plan JSON")
        else:
            c.add_argument("--upload", action="store_true", help="Upload as a private draft after rendering")
        c.set_defaults(func=fn)

    r = sub.add_parser("render", help="Render a saved plan")
    r.add_argument("--plan", required=True)
    r.add_argument("--upload", action="store_true")
    r.set_defaults(func=cmd_render)

    b = sub.add_parser("batch", help="Produce videos from the topics file")
    b.add_argument("--topics", default="topics.txt")
    b.add_argument("--format", choices=["short", "long"], default="short")
    b.add_argument("--limit", type=int)
    b.add_argument("--upload", action="store_true")
    b.add_argument("--stop-on-error", action="store_true")
    b.set_defaults(func=cmd_batch)

    s = sub.add_parser("schedule", help="Run batch on an interval")
    s.add_argument("--topics", default="topics.txt")
    s.add_argument("--format", choices=["short", "long"], default="short")
    s.add_argument("--per-run", type=int, default=1)
    s.add_argument("--interval", default="24h")
    s.add_argument("--upload", action="store_true")
    s.add_argument("--once", action="store_true", help="Single tick then exit (for cron)")
    s.set_defaults(func=cmd_schedule)

    u = sub.add_parser("upload", help="Upload a job to YouTube")
    u.add_argument("--job", help="Job id (default: latest not-yet-uploaded)")
    u.add_argument("--latest", action="store_true", help="Upload the latest job (default)")
    u.set_defaults(func=cmd_upload)

    sub.add_parser("jobs", help="List produced videos").set_defaults(func=cmd_jobs)

    d = sub.add_parser("demo", help="Render a sample video offline")
    d.add_argument("--format", choices=["short", "long"], default="short")
    d.set_defaults(func=cmd_demo)

    sub.add_parser("hf-check", help="Check Higgsfield credentials").set_defaults(func=cmd_hf_check)
    sub.add_parser("hf-models", help="List Higgsfield model presets").set_defaults(func=cmd_hf_models)
    g = sub.add_parser("hf-generate", help="Run one Higgsfield generation (billable)")
    g.add_argument("--model", required=True, help="Preset name from config.yaml or a raw API model id")
    g.add_argument("--prompt", required=True)
    g.add_argument("--duration", type=float)
    g.add_argument("--resolution")
    g.add_argument("--aspect-ratio")
    g.add_argument("--arg", action="append", help="Extra model argument key=value (JSON values allowed)")
    g.add_argument("--download", help="Save the first output to this path")
    g.add_argument("--yes", action="store_true", help="Confirm the billable request")
    g.set_defaults(func=cmd_hf_generate)
    sub.add_parser("hf-usage", help="Summarise Higgsfield credit ledger").set_defaults(func=cmd_hf_usage)
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log("Interrupted.", level="warn")
        return 130
    except Exception as e:
        log(f"{type(e).__name__}: {e}", level="error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
