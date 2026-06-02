#!/usr/bin/env python3
"""Faceless YouTube automation — CLI entry point.

Commands:
  doctor                 Check dependencies and configuration.
  generate               Create a faceless video from a topic (AI script + TTS).
  clip                   Cut Shorts from a long video you have rights to.
  upload                 Upload a rendered video to YouTube (private draft).
  jobs                   List produced videos and their upload status.

Run `python pipeline.py <command> -h` for command-specific options.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from faceless.config import Config, env
from faceless.jobs import Job, JobStore
from faceless.utils import log, which


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    config = Config.load(args.config)
    log(f"Config: {config.path}", level="info")
    ok = True

    # System deps
    for binary in ("ffmpeg", "ffprobe"):
        if which(binary):
            log(f"{binary}: found", level="ok")
        else:
            log(f"{binary}: MISSING (install ffmpeg)", level="error")
            ok = False

    # Python deps
    for mod, label in [
        ("anthropic", "Anthropic SDK"),
        ("faster_whisper", "faster-whisper (clip mode)"),
        ("edge_tts", "edge-tts (generate mode)"),
        ("yt_dlp", "yt-dlp (url sources)"),
        ("googleapiclient", "Google API client (upload)"),
    ]:
        try:
            __import__(mod)
            log(f"{label}: installed", level="ok")
        except ImportError:
            log(f"{label}: not installed", level="warn")

    # Secrets
    if env("ANTHROPIC_API_KEY"):
        log("ANTHROPIC_API_KEY: set", level="ok")
    else:
        log("ANTHROPIC_API_KEY: MISSING (required)", level="error")
        ok = False
    for key in ("PEXELS_API_KEY", "PIXABAY_API_KEY"):
        log(f"{key}: {'set' if env(key) else 'not set (optional)'}",
            level="ok" if env(key) else "info")
    secret_file = env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
    log(f"YouTube OAuth ({secret_file}): {'found' if Path(secret_file).exists() else 'not found (needed for upload)'}",
        level="ok" if Path(secret_file).exists() else "info")

    log("Doctor: OK" if ok else "Doctor: issues found (see above)",
        level="ok" if ok else "error")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------

def cmd_generate(args) -> int:
    from faceless.generate import generate_video
    from faceless.llm import LLM

    config = Config.load(args.config)
    store = JobStore(config.workdir)
    llm = LLM(config)

    log(f"Writing {args.format} script on: {args.topic}", level="step")
    script = llm.write_script(args.topic, video_format=args.format)
    log(f"Title idea: {script.title_idea}", level="ok")

    video_path = generate_video(script, config=config, video_format=args.format)

    log("Generating metadata...", level="step")
    meta = llm.write_metadata(
        video_format=args.format,
        topic_or_transcript=args.topic,
        script_excerpt=script.script[:1500],
    )

    job = Job(
        id=store.new_id("generate"),
        mode="generate",
        video_format=args.format,
        video_path=str(video_path),
        title=meta.title,
        description=meta.description,
        tags=meta.tags,
        topic=args.topic,
        extra={"hashtags": meta.hashtags, "title_idea": script.title_idea},
    )
    store.save(job)
    log(f"Saved job {job.id}", level="ok")
    _print_job_summary(job)

    if args.upload:
        return _do_upload(job, config, store)
    log("Review the render, then: python pipeline.py upload --latest", level="info")
    return 0


# --------------------------------------------------------------------------
# clip
# --------------------------------------------------------------------------

def cmd_clip(args) -> int:
    from faceless.captions import build_srt, subtitles_filter
    from faceless.clipper import cut_clip
    from faceless.llm import LLM
    from faceless.sources import confirm_rights, download_url, ingest_local
    from faceless.transcribe import transcribe

    config = Config.load(args.config)
    store = JobStore(config.workdir)

    source_desc = args.input or args.url or "(none)"
    confirm_rights(i_own_rights=args.i_own_rights, source_desc=source_desc)

    if args.input:
        source = ingest_local(args.input, config.workdir)
    elif args.url:
        source = download_url(args.url, config.workdir)
    else:
        log("Provide --input <file> or --url <url>.", level="error")
        return 2

    segments = transcribe(source, workdir=config.workdir, model_size=args.whisper_model)
    if not segments:
        log("Empty transcript — nothing to clip.", level="error")
        return 1

    llm = LLM(config)
    log("Finding highlight clips...", level="step")
    highlights = llm.find_highlights(
        segments,
        max_clips=config.get("clip.max_clips", 5),
        min_sec=config.get("clip.min_clip_sec", 20),
        max_sec=config.get("clip.max_clip_sec", 59),
    )
    if not highlights.clips:
        log("No highlights found.", level="warn")
        return 1

    captions_on = config.get("captions.enabled", True)
    made = 0
    for i, clip in enumerate(highlights.clips, 1):
        log(f"[{i}/{len(highlights.clips)}] {clip.title} "
            f"({clip.start:.1f}-{clip.end:.1f}s)", level="step")
        stem = f"{source.stem}-clip{i}"

        subs = None
        if captions_on:
            window = [
                s for s in segments
                if s["end"] > clip.start and s["start"] < clip.end
            ]
            srt = build_srt(window, config.workdir / "captions" / f"{stem}.srt",
                            offset=clip.start)
            subs = subtitles_filter(srt, config, "short")

        out_path = config.workdir / "renders" / f"{stem}.mp4"
        cut_clip(
            source, out_path,
            start=clip.start, end=clip.end,
            config=config, video_format="short",
            subtitles_filter=subs,
        )

        clip_text = " ".join(
            s["text"].strip() for s in segments
            if s["end"] > clip.start and s["start"] < clip.end
        )
        meta = llm.write_metadata(
            video_format="short",
            topic_or_transcript=f"{clip.title}\n\n{clip_text[:1500]}",
        )
        job = Job(
            id=store.new_id("clip"),
            mode="clip",
            video_format="short",
            video_path=str(out_path),
            title=meta.title,
            description=meta.description,
            tags=meta.tags,
            source=str(source),
            extra={"hashtags": meta.hashtags, "clip_title": clip.title,
                   "reason": clip.reason},
        )
        store.save(job)
        made += 1

    log(f"Made {made} clip(s). Review them, then upload with "
        "`python pipeline.py upload --latest` (one at a time).", level="ok")
    return 0


# --------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------

def cmd_upload(args) -> int:
    config = Config.load(args.config)
    store = JobStore(config.workdir)

    if args.job:
        job = store.load(args.job)
    elif args.latest:
        job = store.latest(not_uploaded=True)
        if not job:
            log("No un-uploaded jobs found.", level="error")
            return 1
    else:
        log("Specify --latest or --job <id>.", level="error")
        return 2

    if job.uploaded:
        log(f"Job {job.id} already uploaded: https://youtu.be/{job.youtube_id}",
            level="warn")
        return 0
    return _do_upload(job, config, store)


def _do_upload(job: Job, config: Config, store: JobStore) -> int:
    from faceless.youtube import upload as yt_upload

    video_id = yt_upload(job, config)
    job.uploaded = True
    job.youtube_id = video_id
    store.save(job)
    return 0


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

def cmd_jobs(args) -> int:
    config = Config.load(args.config)
    store = JobStore(config.workdir)
    jobs = store.all()
    if not jobs:
        log("No jobs yet.", level="info")
        return 0
    for j in jobs:
        status = (f"uploaded https://youtu.be/{j.youtube_id}"
                  if j.uploaded else "not uploaded")
        print(f"{j.id}  [{j.video_format}/{j.mode}]  {status}")
        print(f"    title: {j.title}")
        print(f"    file:  {j.video_path}")
    return 0


# --------------------------------------------------------------------------

def _print_job_summary(job: Job) -> None:
    print("\n" + "=" * 60)
    print(f"  {job.title}")
    print("=" * 60)
    print(job.description)
    if job.tags:
        print("\nTags: " + ", ".join(job.tags))
    hashtags = job.extra.get("hashtags") or []
    if hashtags:
        print("Hashtags: " + " ".join(hashtags))
    print(f"\nFile: {job.video_path}")
    print("=" * 60 + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="Path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Check deps and config").set_defaults(func=cmd_doctor)

    g = sub.add_parser("generate", help="Create a video from a topic")
    g.add_argument("--topic", required=True, help="What the video is about")
    g.add_argument("--format", choices=["short", "long"], default="short")
    g.add_argument("--upload", action="store_true", help="Upload after rendering")
    g.set_defaults(func=cmd_generate)

    c = sub.add_parser("clip", help="Cut Shorts from a long source video")
    c.add_argument("--input", help="Local source video file")
    c.add_argument("--url", help="URL to download (content you OWN / CC-licensed)")
    c.add_argument("--i-own-rights", action="store_true",
                   help="Affirm you have rights to this source (required)")
    c.add_argument("--whisper-model", default="base",
                   help="tiny|base|small|medium|large-v3")
    c.set_defaults(func=cmd_clip)

    u = sub.add_parser("upload", help="Upload a render to YouTube")
    u.add_argument("--latest", action="store_true", help="Upload most recent un-uploaded job")
    u.add_argument("--job", help="Upload a specific job id")
    u.set_defaults(func=cmd_upload)

    sub.add_parser("jobs", help="List produced videos").set_defaults(func=cmd_jobs)
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log("Interrupted.", level="warn")
        return 130
    except Exception as e:
        log(str(e), level="error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
