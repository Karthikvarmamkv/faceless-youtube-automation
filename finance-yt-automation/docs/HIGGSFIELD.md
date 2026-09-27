# Higgsfield (AI video and image generation)

The project can call any Higgsfield model through the official
`higgsfield-client` Python SDK. It is **off by default**. Stock footage and
local charts cost nothing, while Higgsfield spends credits.

## 1. Add your API key

Create a file named `.env.local` in the project root (next to `pipeline.py`)
and put your key in it, in `key-id:key-secret` format:

```
HF_KEY=your-key-id:your-key-secret
```

- `.env.local` is gitignored, so it is never committed.
- Don't paste the key into chats, issues, or config.yaml.
- Check it without revealing it: `python pipeline.py hf-check`.

The SDK also accepts `HF_API_KEY` plus `HF_API_SECRET` as separate variables.

## 2. Try the SDK example

```bash
python main.py
```

This sends one **billable** request: Seedance 2.5 text-to-video, prompt "A
cinematic scene at sunset", 5 seconds, 720p, 16:9. It waits for completion,
then prints the video URL. A failed, canceled, or moderated request exits
non-zero and says so. Nothing is reported as success unless a video URL came back.

Other models work the same way:

```bash
python main.py --model <api-model-id> --duration 8 --arg generate_audio=false
```

## 3. Model presets and credit prices

Presets live under `higgsfield.models` in `config.yaml`. Each one has:

| Field | Meaning |
|---|---|
| `id` | API model id from the model's API page at https://console.higgsfield.ai/models |
| `defaults` | Arguments sent unless overridden, such as duration, resolution, aspect_ratio |
| `credits_per_second` or `credits_per_request` | Price, copied from the console |

Add any model the console lists. Refer to it by preset name or by raw id:

```bash
python pipeline.py hf-models
python pipeline.py hf-generate --model seedance_t2v --prompt "slow pan over a city at dusk" --yes
python pipeline.py hf-generate --model <api-model-id> --prompt "..." --arg mode=\"fast\" --yes
```

## 4. Budgets and the ledger

```yaml
higgsfield:
  budget:
    max_credits_per_request: 60
    max_credits_per_day: 300
    require_known_cost: true
```

- Every request is estimated from the preset's price before it is sent.
- A request over either budget is refused before anything is billed.
- With `require_known_cost: true`, a model without a price is refused, so
  nothing is ever spent blind. **Fill in the prices after checking the console.**
- Every request is appended to `data/higgsfield_ledger.jsonl` with its
  request id, status, and estimated credits. Summarise it with
  `python pipeline.py hf-usage`.
- The ledger holds estimates. The Higgsfield console is the source of truth for billing.

## 5. Use it for B-roll in videos

```yaml
visuals:
  footage_source: "higgsfield"
  higgsfield_model: "broll_video"   # any preset
  higgsfield_max_clips: 3           # per video; other scenes use a gradient
```

Narration scenes then get a generated clip from their footage prompt. Charts
and stat cards are still rendered locally, so the numbers stay exact.

## Behaviour notes

- `subscribe()` in the SDK returns the final payload even when a request
  fails, is canceled, or is flagged NSFW. This project checks the status and
  raises in those cases instead of treating them as success.
- The SDK retries on HTTP 408, 429, and 5xx, including on submit. A rare server
  error during submit could therefore create a second billable request. The
  daily budget counts every accepted request to limit the impact.
