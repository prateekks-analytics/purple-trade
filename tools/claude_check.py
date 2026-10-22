"""Check a Claude API key on its own, before Purple uses it.

Usage (from the purple folder):
    backend\\.venv\\Scripts\\python.exe tools\\claude_check.py            # key from ANTHROPIC_API_KEY or purple/.env
    backend\\.venv\\Scripts\\python.exe tools\\claude_check.py --model claude-sonnet-5-5

Step 1 (free): the key is valid and the model is available to it.
Step 2 (costs well under one US cent): one tiny message, to see whether the account can actually pay for calls.
The key itself is never printed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}  # $ per 1M tokens, 6 Oct 2026


def load_key() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            k, _, v = line.strip().partition("=")
            if k.strip().removeprefix("export ").strip() == "ANTHROPIC_API_KEY" and v.strip():
                return v.strip().strip('"').strip("'")
    return ""


def explain(e: anthropic.APIStatusError) -> str:
    msg = str(getattr(e, "message", "") or e)
    if e.status_code == 401:
        return "The key was rejected (invalid or revoked). Copy it again from the Claude Console."
    if e.status_code == 402 or getattr(e, "type", "") == "billing_error" or "credit balance" in msg.lower():
        return ("The key is valid but the account has no API credit, so calls can't be paid. "
                "Cloud session credits on a Pro plan do not cover API calls; add API credit in the Claude Console.")
    if e.status_code == 403:
        return "The key is not allowed to use this model or workspace."
    if e.status_code == 404:
        return "This model is not available to the key's organisation."
    if e.status_code == 429:
        return "Rate limited. Wait a minute and run again."
    if e.status_code >= 500:
        return "Anthropic had a server problem. Run again in a minute."
    return f"API error {e.status_code}: {msg[:200]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5-5", choices=sorted(PRICES))
    args = ap.parse_args()
    key = load_key()
    if not key:
        print("No key found. Put ANTHROPIC_API_KEY=... in purple/.env (ignored by git) or set the environment variable.")
        return 2
    client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=60.0)

    print(f"Step 1 (free): is the key valid for {args.model}? ", end="", flush=True)
    try:
        m = client.models.retrieve(args.model)
        print(f"yes ({m.display_name}).")
    except anthropic.APIStatusError as e:
        print("no.\n  " + explain(e))
        return 1
    except anthropic.APIConnectionError:
        print("no.\n  Could not reach api.anthropic.com. Check the internet connection.")
        return 1

    print("Step 2 (tiny paid call): can the account pay for a message? ", end="", flush=True)
    t0 = time.time()
    try:
        r = client.messages.create(
            model=args.model, max_tokens=512, output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word OK."}],
        )
    except anthropic.APIStatusError as e:
        print("no.\n  " + explain(e))
        return 1
    except anthropic.APIConnectionError:
        print("no.\n  Could not reach api.anthropic.com.")
        return 1
    text = "".join(b.text for b in r.content if b.type == "text").strip()
    pin, pout = PRICES[args.model]
    cost = (r.usage.input_tokens * pin + r.usage.output_tokens * pout) / 1_000_000
    print(f"yes, in {time.time() - t0:.1f} s.")
    print(f"  Reply: {text[:40]!r} (stop reason {r.stop_reason})")
    print(f"  Tokens: {r.usage.input_tokens} in, {r.usage.output_tokens} out; about ${cost:.5f} at list price.")
    print("  Check the Claude Console usage page: if this call shows up there, the account's API credit paid for it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
