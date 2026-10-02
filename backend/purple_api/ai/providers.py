"""LLM providers behind one tiny interface so the model can be swapped without touching the app."""
from __future__ import annotations

import os
from typing import Protocol

import httpx


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    model: str

    def status(self) -> dict: ...
    def complete(self, system: str, messages: list[dict]) -> str: ...


class OllamaProvider:
    """Local Ollama. No data leaves the machine; no cost."""

    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: float = 180.0):
        self.model = model or os.environ.get("PURPLE_AI_MODEL", "qwen3:8b")
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout

    def status(self) -> dict:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        except Exception as e:  # noqa: BLE001 - surface any connectivity problem as status
            return {"provider": self.name, "model": self.model, "available": False,
                    "detail": f"Ollama not reachable at {self.base_url} ({type(e).__name__})."}
        ok = self.model in names
        return {"provider": self.name, "model": self.model, "available": ok,
                "detail": "Local model ready." if ok else f"Model {self.model} not installed. Installed: {', '.join(names) or 'none'}."}

    def complete(self, system: str, messages: list[dict]) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"Could not reach Ollama: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
        return r.json()["message"]["content"]


def default_provider() -> Provider:
    # Additional providers (e.g. a paid cloud API) are added here once authorised.
    return OllamaProvider()
