"""Higgsfield generative-media integration (any model, credit-aware).

Wraps the official `higgsfield-client` SDK with what an automated channel
needs on top of it:

- A model registry in config.yaml (`higgsfield.models`), so you can switch
  between Seedance, Kling, Veo, image models, etc. by name instead of
  hardcoding one model into the code.
- Credit accounting: every request is estimated before it is sent, checked
  against per-request and per-day budgets, and written to a local ledger
  (<workdir>/higgsfield_ledger.jsonl) with its outcome.
- Honest outcomes: `subscribe()` returns the final JSON even when a request
  failed, was cancelled, or was flagged NSFW. This module checks the final
  status and raises instead of pretending the request succeeded.

Credentials: HF_KEY="key-id:key-secret" (or HF_API_KEY + HF_API_SECRET), read
from the environment, `.env.local`, or `.env`. Values are never printed or
logged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import ROOT, Config
from .utils import log

# Terminal statuses reported by the Higgsfield API.
SUCCESS = "completed"
FAILURE_STATUSES = {"failed", "nsfw", "canceled", "cancelled"}


class HiggsfieldError(RuntimeError):
    """Base error for this integration."""


class CredentialsError(HiggsfieldError):
    pass


class BudgetError(HiggsfieldError):
    pass


class GenerationFailed(HiggsfieldError):
    def __init__(self, status: str, request_id: str | None, detail: str = ""):
        self.status = status
        self.request_id = request_id
        msg = f"Higgsfield request {request_id or '(unknown id)'} ended with status '{status}'"
        super().__init__(msg + (f": {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def load_env_files() -> None:
    """Load .env.local then .env (without overriding real env vars)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for name in (".env.local", ".env"):
        path = ROOT / name
        if path.exists():
            load_dotenv(path, override=False)


def credential_status() -> str:
    """Describe the credential state WITHOUT revealing any value."""
    load_env_files()
    key = os.environ.get("HF_KEY", "").strip()
    if key:
        left, sep, right = key.partition(":")
        if not sep or not left or not right:
            return "malformed (HF_KEY must be key-id:key-secret)"
        return "set (HF_KEY)"
    if os.environ.get("HF_API_KEY", "").strip() and os.environ.get("HF_API_SECRET", "").strip():
        return "set (HF_API_KEY + HF_API_SECRET)"
    return "missing"


def require_credentials() -> None:
    state = credential_status()
    if not state.startswith("set"):
        raise CredentialsError(
            f"Higgsfield credentials {state}. Add HF_KEY=key-id:key-secret to "
            ".env.local in the project root (it is gitignored). See docs/HIGGSFIELD.md."
        )


# ---------------------------------------------------------------------------
# Model registry + cost estimation
# ---------------------------------------------------------------------------

@dataclass
class ModelPreset:
    name: str
    id: str                                  # API application id, e.g. bytedance/seedance-2.5/text-to-video
    output: str = "video"                    # video | image | audio
    defaults: dict[str, Any] = field(default_factory=dict)
    credits_per_second: float | None = None  # for duration-billed models
    credits_per_request: float | None = None # for flat-priced models
    notes: str = ""

    def estimate_credits(self, arguments: dict[str, Any]) -> float | None:
        if self.credits_per_request is not None:
            return float(self.credits_per_request)
        if self.credits_per_second is not None:
            duration = arguments.get("duration", self.defaults.get("duration"))
            if duration is None:
                return None
            return float(self.credits_per_second) * float(duration)
        return None


def model_presets(config: Config) -> dict[str, ModelPreset]:
    presets = {}
    for name, spec in (config.get("higgsfield.models") or {}).items():
        spec = spec or {}
        if not spec.get("id"):
            continue
        presets[name] = ModelPreset(
            name=name,
            id=spec["id"],
            output=spec.get("output", "video"),
            defaults=dict(spec.get("defaults") or {}),
            credits_per_second=spec.get("credits_per_second"),
            credits_per_request=spec.get("credits_per_request"),
            notes=spec.get("notes", ""),
        )
    return presets


def resolve_model(config: Config, model: str) -> ModelPreset:
    """Look up a preset by name; a raw API id (contains '/') is also accepted."""
    presets = model_presets(config)
    if model in presets:
        return presets[model]
    for p in presets.values():
        if p.id == model:
            return p
    if "/" in model:
        return ModelPreset(name=model, id=model)
    raise HiggsfieldError(
        f"Unknown Higgsfield model '{model}'. Configured presets: "
        f"{', '.join(presets) or '(none)'}. Add it under higgsfield.models in config.yaml."
    )


# ---------------------------------------------------------------------------
# Ledger + budget
# ---------------------------------------------------------------------------

class Ledger:
    """Append-only JSONL record of every Higgsfield request."""

    def __init__(self, workdir: Path):
        self.path = Path(workdir) / "higgsfield_ledger.jsonl"

    def append(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def credits_today(self) -> float:
        """Estimated credits of today's (UTC) requests that were accepted.

        Counts completed requests and requests that were submitted but whose
        outcome is unknown, since those may have been billed.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        total = 0.0
        for e in self.entries():
            if not str(e.get("ts", "")).startswith(today):
                continue
            if e.get("status") in ("completed", "submitted", "error_after_submit"):
                total += float(e.get("estimated_credits") or 0)
        return total


def check_budget(config: Config, estimate: float | None, ledger: Ledger) -> None:
    per_request = config.get("higgsfield.budget.max_credits_per_request")
    per_day = config.get("higgsfield.budget.max_credits_per_day")
    require_known = bool(config.get("higgsfield.budget.require_known_cost", True))

    if estimate is None:
        if require_known:
            raise BudgetError(
                "This model has no credit price in config.yaml, so its cost can't be "
                "checked against your budget. Add credits_per_second or "
                "credits_per_request to the preset (copy the price from the Higgsfield "
                "console), or set higgsfield.budget.require_known_cost: false."
            )
        log("Credit cost unknown for this model; budget check skipped.", level="warn")
        return
    if per_request is not None and estimate > float(per_request):
        raise BudgetError(
            f"Estimated {estimate:g} credits exceeds max_credits_per_request ({per_request})."
        )
    if per_day is not None:
        spent = ledger.credits_today()
        if spent + estimate > float(per_day):
            raise BudgetError(
                f"Daily budget reached: {spent:g} spent today + {estimate:g} estimated "
                f"> max_credits_per_day ({per_day})."
            )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    request_id: str | None
    model_id: str
    status: str
    urls: list[str]
    estimated_credits: float | None
    raw: dict[str, Any]


def extract_media_urls(data: Any) -> list[str]:
    """Collect output media URLs from a result payload, whatever its shape.

    Handles shapes like {"video": {"url": ...}}, {"videos": [{"url": ...}]},
    {"images": [{"url": ...}]}, and nested variants.
    """
    urls: list[str] = []

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and node.startswith(("http://", "https://")):
            if key in ("url", "video_url", "image_url", "audio_url", "uri") or key.endswith("_url"):
                if not key.endswith(("status_url", "cancel_url", "response_url")) and node not in urls:
                    urls.append(node)

    walk(data)
    return urls


def generate(
    config: Config,
    model: str,
    arguments: dict[str, Any],
    *,
    purpose: str = "",
    on_status: Callable[[str], None] | None = None,
) -> GenerationResult:
    """Run one Higgsfield generation with budget checks and ledger records.

    Raises CredentialsError, BudgetError, or GenerationFailed. Returns only on
    a completed request that produced at least one media URL.
    """
    preset = resolve_model(config, model)
    args = {**preset.defaults, **{k: v for k, v in arguments.items() if v is not None}}
    estimate = preset.estimate_credits(args)
    ledger = Ledger(config.workdir)

    require_credentials()
    check_budget(config, estimate, ledger)

    try:
        import higgsfield_client
    except ImportError as e:
        raise HiggsfieldError("higgsfield-client not installed. `pip install higgsfield-client`.") from e

    request_id: dict[str, str | None] = {"id": None}
    last_status: dict[str, str] = {"s": ""}

    def on_enqueue(rid: str) -> None:
        request_id["id"] = rid
        ledger.append(_entry(preset, args, estimate, purpose, rid, "submitted"))
        log(f"Higgsfield request queued: {rid}", level="info")

    def on_update(status: Any) -> None:
        name = type(status).__name__.lower()
        if name != last_status["s"]:
            last_status["s"] = name
            log(f"  higgsfield status: {name}", level="info")
            if on_status:
                on_status(name)

    log(f"Submitting to {preset.id} "
        f"(est. {estimate:g} credits)" if estimate is not None else f"Submitting to {preset.id}",
        level="step")
    try:
        result = higgsfield_client.subscribe(
            preset.id, arguments=args, on_enqueue=on_enqueue, on_queue_update=on_update,
        )
    except Exception as e:
        status = "error_after_submit" if request_id["id"] else "error_before_submit"
        ledger.append(_entry(preset, args, estimate, purpose, request_id["id"], status,
                             error=type(e).__name__))
        raise HiggsfieldError(f"Higgsfield request failed: {e}") from e

    status = str((result or {}).get("status", "")).lower()
    rid = request_id["id"] or (result or {}).get("request_id")
    urls = extract_media_urls(result) if status == SUCCESS else []

    if status != SUCCESS or not urls:
        final = status or "unknown"
        if status == SUCCESS and not urls:
            final = "completed_without_media"
        ledger.append(_entry(preset, args, estimate, purpose, rid, final))
        detail = str((result or {}).get("error") or (result or {}).get("detail") or "")
        raise GenerationFailed(final, rid, detail)

    ledger.append(_entry(preset, args, estimate, purpose, rid, SUCCESS, urls=urls))
    return GenerationResult(request_id=rid, model_id=preset.id, status=status, urls=urls,
                            estimated_credits=estimate, raw=result)


def _entry(preset: ModelPreset, args: dict[str, Any], estimate: float | None, purpose: str,
           request_id: str | None, status: str, **extra: Any) -> dict[str, Any]:
    safe_args = {k: v for k, v in args.items() if k != "prompt"}
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": preset.name,
        "model_id": preset.id,
        "request_id": request_id,
        "status": status,
        "estimated_credits": estimate,
        "purpose": purpose,
        "prompt": str(args.get("prompt", ""))[:200],
        "args": safe_args,
        **extra,
    }


def download(url: str, dest: Path) -> Path:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    return dest
