"""LLM providers behind one tiny interface so the model can be swapped without touching the app."""
from __future__ import annotations

import os
import time
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
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192},
        }
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"Could not reach Ollama: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
        return r.json()["message"]["content"]


class GeminiProvider:
    """Google Gemini through the free-tier API key of whoever runs the app (GOOGLE_API_KEY). Text is sent to Google."""

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: float = 120.0,
                 fallback: str | None = None, retry_wait: float = 2.0):
        self.model = model or os.environ.get("PURPLE_GEMINI_MODEL", "gemini-3.8-flash")
        # used once when the main model is overloaded (503) — free-tier demand spikes are common
        self.fallback = fallback if fallback is not None else os.environ.get("PURPLE_GEMINI_FALLBACK", "gemini-3.7-flash")
        self.retry_wait = retry_wait
        self._key = api_key if api_key is not None else os.environ.get("GOOGLE_API_KEY", "")
        self.timeout = timeout

    def status(self) -> dict:
        ok = bool(self._key)
        return {"provider": self.name, "model": self.model, "available": ok,
                "detail": "Google Gemini, free tier. Text you send to the AI goes to Google." if ok
                else "Set GOOGLE_API_KEY (see README, 'Use Google Gemini') and restart Purple."}

    def complete(self, system: str, messages: list[dict]) -> str:
        if not self._key:
            raise ProviderError("GOOGLE_API_KEY is not set.")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                         for m in messages],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        attempts = [self.model, self.model] + ([self.fallback] if self.fallback and self.fallback != self.model else [])
        for i, model in enumerate(attempts):
            try:
                r = httpx.post(self.URL.format(model=model), json=body, timeout=self.timeout,
                               headers={"x-goog-api-key": self._key})
            except httpx.HTTPError as e:
                raise ProviderError(f"Could not reach Google Gemini: {type(e).__name__}") from e
            if r.status_code not in (500, 503) or i == len(attempts) - 1:
                break
            time.sleep(self.retry_wait)
        if r.status_code in (500, 503):
            raise ProviderError("Google Gemini is overloaded right now (free tier). Try again in a minute.")
        if r.status_code == 429:
            raise ProviderError("Gemini free-tier limit reached. Wait a minute and try again.")
        if r.status_code >= 400:
            raise ProviderError(f"Gemini error {r.status_code}: {r.text[:200]}")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError("Gemini returned no answer (it may have been blocked).") from e
        return "".join(p.get("text", "") for p in parts)


def default_provider() -> Provider:
    """PURPLE_AI_PROVIDER=gemini|ollama picks one; otherwise Gemini when GOOGLE_API_KEY is set, else local Ollama."""
    choice = os.environ.get("PURPLE_AI_PROVIDER", "").strip().lower()
    if choice == "ollama" or (choice != "gemini" and not os.environ.get("GOOGLE_API_KEY")):
        return OllamaProvider()
    return GeminiProvider()
