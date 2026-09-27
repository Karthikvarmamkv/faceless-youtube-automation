# Finance Faceless YouTube Automation

A self-contained pipeline for running a **faceless personal-finance YouTube
channel**: Claude plans and writes each video, the numbers are computed by code
(never by the model), every script passes a two-layer compliance review, and
the finished video lands on YouTube as a **private draft** for you to check.

> Read [`docs/RESPONSIBLE_USE.md`](docs/RESPONSIBLE_USE.md) before publishing.
> Finance content has extra legal and platform risk. This tool reduces that
> risk. It does not remove it.

## How a video gets made

```
topic ──► Claude plans scenes ──► code computes every number ──► Claude fact-checks
          (narration / chart /     (compound growth, debt        + compliance-edits
           stat, per scene)         payoff, inflation, bars)     against the real numbers
                                                                        │
             rule-based compliance scanner runs before AND after ◄──────┘
                                   │  (critical violation = render blocked)
                                   ▼
   per scene: TTS voiceover ─► animated chart / stat card / footage ─► ASS captions
                                   │
                                   ▼
          concat + optional music ─► thumbnail ─► SEO metadata + chapters
                                   ▼
          description gets disclaimer + AI disclosure ─► private YouTube draft
```

What makes it finance-specific:

- **Accurate numbers.** Claude picks the scenario, such as $200 a month at 7%
  for 30 years. `finance_channel/finance_math.py` does the arithmetic, and the
  script review corrects the narration to match.
- **Animated data charts.** Compound growth, debt payoff, inflation erosion,
  and bar comparisons draw themselves on screen, with the assumption printed.
- **Compliance gate.** A regex scanner catches guaranteed returns, "risk-free",
  ticker buy/sell calls, get-rich-quick framing, and price predictions. A
  Claude review pass handles the nuance. Unfixed critical issues block the render.
- **Disclosures built in.** A short spoken disclaimer, a full description
  disclaimer, an AI disclosure, and YouTube's synthetic-media flag.
- **Fact-check list.** Every job records the claims a human should verify.
- **Chapters and thumbnails** for long-form videos.
- **Optional Higgsfield AI video**, using any model, with credit budgets and a
  usage ledger. See [`docs/HIGGSFIELD.md`](docs/HIGGSFIELD.md).

## Quick start

```bash
# 1. System dependency: ffmpeg (brew install ffmpeg / sudo apt install ffmpeg)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env                 # ANTHROPIC_API_KEY, optional PEXELS_API_KEY
cp config.example.yaml config.yaml   # channel name, niche, pillars, voice, budgets

# 3. Check setup, then render a sample video with no API keys
python pipeline.py doctor
python pipeline.py demo

# 4. Real videos
python pipeline.py plan --topic "avalanche vs snowball debt payoff"   # script + review only
python pipeline.py make --topic "the 50/30/20 budget" --format short  # full render
python pipeline.py jobs                                               # review + fact-check list
python pipeline.py upload --job <job-id>                              # private draft
```

Full walkthrough: [`docs/SETUP.md`](docs/SETUP.md).

## Topic queue and scheduling

```bash
cp topics.example.txt topics.txt
python pipeline.py ideas --count 15 --append       # Claude brainstorms per pillar
python pipeline.py batch --limit 3 --format short
python pipeline.py schedule --per-run 1 --once     # one tick, for cron
```

Lines in `topics.txt` can be tagged with a pillar: `debt payoff strategies | avalanche vs snowball`.
Produced topics are tracked in `data/topics_state.json`, so reruns never repeat work.

Example cron entry, one Short a day at 9am as a private draft:

```cron
0 9 * * *  cd /path/to/finance-yt-automation && .venv/bin/python pipeline.py schedule --per-run 1 --once --upload
```

## Commands

| Command | What it does |
|---|---|
| `doctor` | Check ffmpeg, packages, and keys |
| `ideas` | Brainstorm topics per content pillar; `--append` adds them to `topics.txt` |
| `plan` | Script, compute numbers, review, save plan JSON; no rendering |
| `render` | Render a saved plan |
| `make` | `plan` + `render`; `--upload` for a private draft |
| `batch` / `schedule` | Produce from the topics queue, once or on an interval |
| `upload` | Upload a job as a private or unlisted draft |
| `jobs` | List jobs, review status, and claims to verify |
| `demo` | Offline sample render with no API keys |
| `hf-check` / `hf-models` / `hf-generate` / `hf-usage` | Higgsfield credentials, model presets, one-off generation, and the credit ledger |

## Project layout

| Path | Purpose |
|---|---|
| `pipeline.py` | CLI |
| `main.py` | Minimal Higgsfield SDK example (Seedance 2.5 by default, any model via flags) |
| `finance_channel/llm.py` | Claude: ideas, scene plans, compliance review, metadata |
| `finance_channel/schemas.py` | Structured-output schemas |
| `finance_channel/finance_math.py` | Compound growth, debt payoff, inflation math |
| `finance_channel/compliance.py` | Rule-based compliance scanner |
| `finance_channel/charts.py` | Animated charts, stat cards, thumbnails |
| `finance_channel/render.py` | Scene rendering, concat, music, chapters |
| `finance_channel/producer.py` | Orchestration and the compliance gate |
| `finance_channel/higgsfield.py` | Higgsfield models, budgets, ledger |
| `finance_channel/footage.py` | Pexels, Pixabay, or Higgsfield B-roll |
| `finance_channel/tts.py`, `captions.py` | Voiceover and captions |
| `finance_channel/youtube.py` | Upload with synthetic-media flag and thumbnail |
| `tests/` | Unit tests (`pytest`) |

## Costs at a glance

- **Anthropic API**: a plan, a review, and metadata cost a few cents per Short.
- **edge-tts**: free.
- **Pexels / Pixabay**: free with an API key.
- **Higgsfield**: paid credits. Off by default, and capped by the budgets in `config.yaml`.
- **YouTube Data API**: free quota. About 1,600 units per upload, so roughly 6 uploads a day.
