# Setup guide

End-to-end setup for the faceless YouTube pipeline.

## 1. System dependency: ffmpeg

ffmpeg does the actual video cutting, reframing, and caption burn-in. It is
**not** a pip package.

| OS | Command |
|----|---------|
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt update && sudo apt install ffmpeg` |
| Windows | Download from https://www.gyan.dev/ffmpeg/builds/ and add `bin/` to PATH |

Verify: `ffmpeg -version` and `ffprobe -version`.

## 2. Python environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> `faster-whisper` will download a model on first use. The default `base` model
> is ~140 MB. CPU works; an NVIDIA GPU is much faster.

## 3. Configuration

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `config.yaml` to set your channel **niche**, **tone**, and **audience** —
these steer Claude's scripting and metadata. Edit `.env` for your API keys.

### Anthropic API key (required)

1. Go to https://console.anthropic.com/settings/keys
2. Create a key, put it in `.env` as `ANTHROPIC_API_KEY=sk-ant-...`

### Stock footage keys (optional, for `generate` mode)

Free keys give the generated videos real background footage instead of a solid
color:

- Pexels: https://www.pexels.com/api/ → `PEXELS_API_KEY`
- Pixabay: https://pixabay.com/api/docs/ → `PIXABAY_API_KEY`

Pick which one via `config.yaml` → `generate.footage_source`.

## 4. YouTube upload (OAuth)

Uploading requires a Google OAuth "Desktop app" client.

1. Go to https://console.cloud.google.com/ and create (or pick) a project.
2. **APIs & Services → Library →** enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen →** configure it. While in
   *Testing* mode, add your own Google account under **Test users**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →**
   Application type **Desktop app**. Download the JSON.
5. Save it as `client_secret.json` in the project root (or point
   `YOUTUBE_CLIENT_SECRET_FILE` at it in `.env`).

First upload opens a browser to authorize; the token is cached in `token.json`
for next time. Both files are gitignored.

> **Quota:** each upload costs ~1600 of the default 10,000 daily quota units
> (~6 uploads/day). Request more in the Cloud Console if needed.

## 5. Verify everything

```bash
python pipeline.py doctor
```

Green checks for ffmpeg + `ANTHROPIC_API_KEY` are the minimum to start.

## 6. First runs

```bash
# Generate a Short from an idea
python pipeline.py generate --topic "why discipline beats motivation" --format short

# Cut Shorts from a long video you own
python pipeline.py clip --input ~/Videos/my_podcast.mp4 --i-own-rights

# Review the files in data/renders/, then upload one as a private draft
python pipeline.py jobs
python pipeline.py upload --latest
```

## Captions / fonts

Caption styling lives under `captions:` in `config.yaml`. The `font` must be a
font ffmpeg's libass can find on your system (e.g. `Arial`, `DejaVu Sans`,
`Impact`). On Linux you may need `sudo apt install fonts-dejavu`.

## Troubleshooting

- **`ffmpeg/ffprobe not found`** — install ffmpeg (step 1) and reopen your shell.
- **`Missing ANTHROPIC_API_KEY`** — set it in `.env`; confirm with `doctor`.
- **Whisper is slow** — use `--whisper-model tiny` for speed, or a GPU machine.
- **Captions not showing** — check the `font` exists; try `DejaVu Sans`.
- **Upload 403 / not a test user** — add your account under OAuth *Test users*.
- **No footage in generated videos** — add a Pexels/Pixabay key, or it falls
  back to a solid background by design.
