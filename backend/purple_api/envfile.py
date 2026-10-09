"""Minimal .env reader (no extra dependency). Values already set in the environment win."""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"  # purple/.env, ignored by git


def load_env(path: Path = ENV_FILE) -> list[str]:
    """Load KEY=VALUE lines into os.environ; returns the names loaded (never the values)."""
    if not path.is_file():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
