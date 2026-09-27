# Setup

## 1. ffmpeg

| OS | Command |
|---|---|
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg fonts-dejavu` |
| Windows | https://www.gyan.dev/ffmpeg/builds/ (add `bin/` to PATH) |

## 2. Python

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.10 or newer.

## 3. Keys and config

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

| Key | Where | Needed for |
|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` | `ideas`, `plan`, `make`, `batch` (https://console.anthropic.com/settings/keys) |
| `PEXELS_API_KEY` or `PIXABAY_API_KEY` | `.env` | Stock footage; without it narration scenes use a gradient |
| `HF_KEY` | `.env.local` | Optional Higgsfield AI video (see HIGGSFIELD.md) |
| `client_secret.json` | project root | YouTube upload |

In `config.yaml`, set at least:

- `channel.name`, `niche`, `tone`, `target_audience`, `region`, `currency_symbol`
- `pillars`: 4 to 8 content themes, used by `ideas`
- `voiceover.voice`: list options with `edge-tts --list-voices`
- `compliance.affiliate_disclosure` if you use affiliate links

## 4. YouTube upload (OAuth)

1. In https://console.cloud.google.com/, create a project and enable **YouTube Data API v3**.
2. Configure the **OAuth consent screen**. In testing mode, add your Google account as a test user.
3. Create **Credentials → OAuth client ID → Desktop app** and download the JSON.
4. Save it as `client_secret.json` in the project root.

The first upload opens a browser to authorize. The token is cached in `token.json`.
Both files are gitignored. Custom thumbnails need a verified channel.

## 5. Verify

```bash
python pipeline.py doctor
python pipeline.py demo            # renders data/renders/<...>.mp4 with no keys
python -m pytest -q                # unit tests (pip install pytest)
```

## Troubleshooting

- **No voice in the demo.** edge-tts needs internet access to Microsoft's speech service. Behind a proxy, set `HTTPS_PROXY` and `SSL_CERT_FILE`.
- **Captions missing.** Check that `captions.font` exists. `DejaVu Sans` is a safe choice on Linux.
- **"Script blocked by compliance check".** Run `plan` to see the flagged phrase, then rephrase the topic or edit the saved plan JSON and `render` it.
- **Short over 60 seconds.** Pick a narrower topic, or raise `voiceover.rate` to `+8%`.
