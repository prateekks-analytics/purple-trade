"""Importing user-supplied agents (trading bots). Uploaded code is only read, never executed."""
from __future__ import annotations

import json
from pathlib import PurePath

from pydantic import ValidationError

from .schema import Strategy

MAX_BYTES = 200 * 1024
MAX_AI_CHARS = 16_000  # keeps prompt + file inside the local model's context window
CODE_EXTENSIONS = {".py", ".pine", ".txt", ".md", ".js", ".ts", ".mq4", ".mq5", ".mql", ".cs", ".java", ".r", ".ipynb"}
EXPORT_FORMAT = "purple-strategy"


class AgentError(ValueError):
    pass


def decode_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Return (kind, text). kind is 'purple-json' or 'code'."""
    if not data:
        raise AgentError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise AgentError("The file is larger than 200 KB.")
    if b"\x00" in data[:4096]:
        raise AgentError("This looks like a binary file. Upload source code (.py, .pine, …) or a Purple strategy .json.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    ext = PurePath(filename or "").suffix.lower()
    if ext == ".json":
        return "purple-json", text
    if ext == ".ipynb":
        return "code", _notebook_code(text)
    if ext and ext not in CODE_EXTENSIONS:
        raise AgentError(f"Unsupported file type '{ext}'. Use .json (Purple strategy) or a source file such as "
                         ".py, .pine, .js, .mq5 or .txt.")
    return "code", text


def parse_purple_json(text: str) -> Strategy:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AgentError(f"Not valid JSON (line {e.lineno}).") from None
    if isinstance(data, dict) and isinstance(data.get("strategy"), dict):
        data = data["strategy"]
    try:
        return Strategy.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise AgentError(f"JSON is not a Purple strategy ({loc}: {first['msg']}). "
                         "Code files are translated by the AI instead — upload the bot's source.") from None


def export_payload(strategy: dict) -> dict:
    return {"format": EXPORT_FORMAT, "version": 1, "strategy": strategy}


def check_code_size(text: str) -> None:
    if len(text) > MAX_AI_CHARS:
        raise AgentError(f"The code is {len(text):,} characters; the local AI can read about {MAX_AI_CHARS:,}. "
                         "Upload just the file that contains the buy/sell logic.")
    if not text.strip():
        raise AgentError("The file has no readable content.")


def _notebook_code(text: str) -> str:
    try:
        nb = json.loads(text)
        cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        return "\n\n".join("".join(c.get("source", [])) for c in cells)
    except (json.JSONDecodeError, AttributeError):
        raise AgentError("Could not read the notebook.") from None
