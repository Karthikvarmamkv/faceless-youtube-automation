# Faceless YouTube Automation

An automated, Claude-powered pipeline for producing **faceless** YouTube videos —
both by **clipping long videos** into short-form content and by **generating
videos from scratch** (AI script → voiceover → footage → captions) — then
uploading them to your channel as **private/unlisted drafts for your review**.

> ⚠️ **Read [`docs/RESPONSIBLE_USE.md`](docs/RESPONSIBLE_USE.md) first.** This tool
> can only legally use content you own, content you've licensed, or royalty-free /
> Creative Commons material with proper attribution. Re-uploading other people's
> videos risks copyright strikes, demonetization, and channel termination. The
> pipeline forces an explicit per-source **rights confirmation** before it will
> process anything.

## What it does

```
                         ┌──────────────────────────────────────────┐
                         │             faceless pipeline            │
                         └──────────────────────────────────────────┘

  CLIP MODE (long video → Shorts)        GENERATE MODE (idea → video)
  ─────────────────────────────          ──────────────────────────────
  1. ingest source video                 1. Claude writes a script
  2. transcribe (Whisper)                2. TTS voiceover (edge-tts)
  3. Claude finds the best moments       3. assemble background footage
  4. ffmpeg cuts + reframes to 9:16      4. burn-in animated captions
  5. burn-in captions                    5. (optional) auto-cut Shorts
            │                                       │
            └──────────────┬────────────────────────┘
                           ▼
              Claude writes title/description/tags
                           ▼
            upload to YouTube as PRIVATE draft
                           ▼
               you review → publish manually
```

- **Hybrid**: supports clipping AND fully generated content.
- **Both formats**: vertical Shorts (9:16) and long-form (16:9).
- **Draft-first**: every upload lands as `private` (or `unlisted`) so nothing
  goes public without you.
- **Claude-powered**: scripting, highlight detection, and SEO metadata all use
  the Anthropic API (`claude-opus-4-8`).

## Quick start

```bash
# 1. System dependency (required): ffmpeg
#    macOS:   brew install ffmpeg
#    Ubuntu:  sudo apt install ffmpeg
#    Windows: https://www.gyan.dev/ffmpeg/builds/

# 2. Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env            # add your API keys
cp config.example.yaml config.yaml

# 4. See what's wired up
python pipeline.py doctor

# 5a. Generate a faceless video from an idea
python pipeline.py generate --topic "3 stoic habits that change your life" --format short

# 5b. Clip a long video you own into Shorts
python pipeline.py clip --input /path/to/your/podcast.mp4 --i-own-rights

# 6. Upload the most recent render as a private draft
python pipeline.py upload --latest
```

Full setup walkthrough: [`docs/SETUP.md`](docs/SETUP.md).

## Project layout

| Path | Purpose |
|------|---------|
| `pipeline.py` | CLI entry point (`doctor`, `generate`, `clip`, `upload`, `jobs`) |
| `faceless/config.py` | Config + secrets loading |
| `faceless/llm.py` | Claude client — scripts, highlight detection, **and** SEO metadata, with prompt caching |
| `faceless/sources.py` | Source ingest, rights gate, stock-footage fetch |
| `faceless/transcribe.py` | Whisper transcription |
| `faceless/clipper.py` | ffmpeg cutting, 9:16 reframing |
| `faceless/tts.py` | Voiceover generation (edge-tts) |
| `faceless/captions.py` | Subtitle generation + burn-in |
| `faceless/generate.py` | From-scratch video assembly |
| `faceless/youtube.py` | YouTube Data API upload (private/unlisted) |
| `faceless/jobs.py` | Job state tracking |

## Cost & dependencies at a glance

- **Anthropic API** — paid, per token. Scripting + metadata for one video is a
  few cents.
- **Whisper** (`faster-whisper`) — free, runs locally (CPU works; GPU faster).
- **edge-tts** — free Microsoft Edge neural voices.
- **YouTube Data API** — free quota; uploads cost ~1600 quota units each
  (≈6 uploads/day on the default 10k quota).
- **Stock footage** (Pexels/Pixabay) — free with an API key, for the generate mode.

See [`docs/RESPONSIBLE_USE.md`](docs/RESPONSIBLE_USE.md) for the legal/ToS guardrails.
