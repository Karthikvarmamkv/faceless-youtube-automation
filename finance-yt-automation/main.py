#!/usr/bin/env python3
"""Higgsfield SDK example: text-to-video with the official `subscribe` method.

Defaults match the Higgsfield quickstart (Seedance 2.5, 5 s, 720p, 16:9), but
any model works: pass --model with another API model id and --arg for any
model-specific parameters.

    python main.py
    python main.py --model <provider/model/task> --duration 8 --arg generate_audio=false

Credentials: HF_KEY="key-id:key-secret" in .env.local (gitignored). The value
is loaded at runtime and never printed.

This makes a BILLABLE generation request.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULT_MODEL = "bytedance/seedance-2.5/text-to-video"
SUCCESS = "completed"
FAILED = {"failed": "failed", "nsfw": "was moderated (NSFW)", "canceled": "was canceled",
          "cancelled": "was canceled"}


def load_credentials() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for name in (".env.local", ".env"):
        if (ROOT / name).exists():
            load_dotenv(ROOT / name, override=False)


def media_urls(data) -> list[str]:
    """Find output media URLs in the result, whatever its exact shape."""
    found: list[str] = []

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif (isinstance(node, str) and node.startswith("http")
              and (key == "url" or key.endswith("_url"))
              and not key.endswith(("status_url", "cancel_url", "response_url"))):
            found.append(node)

    walk(data)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--prompt", default="A cinematic scene at sunset")
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--resolution", default="720p")
    ap.add_argument("--aspect-ratio", default="16:9")
    ap.add_argument("--arg", action="append", default=[], help="extra key=value (JSON values allowed)")
    args = ap.parse_args()

    load_credentials()
    import higgsfield_client
    from higgsfield_client import CredentialsMissedError, HiggsfieldClientError

    arguments = {"prompt": args.prompt, "duration": args.duration,
                 "resolution": args.resolution, "aspect_ratio": args.aspect_ratio}
    for kv in args.arg:
        k, _, v = kv.partition("=")
        try:
            arguments[k] = json.loads(v)
        except json.JSONDecodeError:
            arguments[k] = v

    request_id = {"id": None}

    def on_enqueue(rid: str) -> None:
        request_id["id"] = rid
        print(f"Queued request {rid}", file=sys.stderr)

    def on_update(status) -> None:
        print(f"Status: {type(status).__name__}", file=sys.stderr)

    try:
        result = higgsfield_client.subscribe(
            args.model, arguments=arguments, on_enqueue=on_enqueue, on_queue_update=on_update,
        )
    except CredentialsMissedError:
        print("Higgsfield credentials missing. Add HF_KEY=key-id:key-secret to .env.local.",
              file=sys.stderr)
        return 2
    except HiggsfieldClientError as e:
        print(f"Higgsfield API error: {e}", file=sys.stderr)
        return 1

    status = str(result.get("status", "")).lower()
    if status in FAILED:
        print(f"Request {request_id['id']} {FAILED[status]}. No video was produced.", file=sys.stderr)
        return 1
    if status != SUCCESS:
        print(f"Request {request_id['id']} ended with unexpected status '{status}'.", file=sys.stderr)
        return 1
    urls = media_urls(result)
    if not urls:
        print("Request completed but no video URL was found in the response:", file=sys.stderr)
        print(json.dumps({k: v for k, v in result.items() if k != "input"}, indent=2), file=sys.stderr)
        return 1
    for url in urls:
        print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
