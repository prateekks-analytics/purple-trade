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
        fb = fallback if fallback is not None else os.environ.get(
            "PURPLE_GEMINI_FALLBACK", "gemini-3.7-flash,gemini-3.5-flash,gemini-flash-lite-latest")
        self.fallbacks = [m.strip() for m in fb.split(",") if m.strip() and m.strip() != self.model]
        self.retry_wait = retry_wait
        self._key = api_key if api_key is not None else os.environ.get("GOOGLE_API_KEY", "")
        self.timeout = timeout

    def status(self) -> dict:
        ok = bool(self._key)
        return {"provider": self.name, "model": self.model, "available": ok,
                "detail": "Google Gemini, free tier. Text you send to the AI goes to Google." if ok
                else "Set GOOGLE_API_KEY (see README, 'Use Google Gemini') and restart Purple."}

    def list_models(self) -> list[str]:
        r = _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": self._key})
        return [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m["name"]
                and not any(x in m["name"] for x in ("tts", "image", "embedding", "live"))]

    def complete(self, system: str, messages: list[dict]) -> str:
        if not self._key:
            raise ProviderError("GOOGLE_API_KEY is not set.")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                         for m in messages],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        attempts = [self.model, self.model, *self.fallbacks]
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


class OpenAICompatProvider:
    """OpenAI, Groq and OpenRouter all speak the OpenAI chat-completions API."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self.name, self.base_url, self._key, self.model, self.timeout = name, base_url.rstrip("/"), api_key, model, timeout

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self._key}"}
        if self.name == "openrouter":
            h["X-Title"] = "Purple Trade"
        return h

    def status(self) -> dict:
        return {"provider": self.name, "model": self.model, "available": bool(self._key), "detail": f"{self.name} key from this browser."}

    def list_models(self) -> list[str]:
        r = _get(f"{self.base_url}/models", self._headers())
        return sorted(m["id"] for m in r.json().get("data", []))

    def complete(self, system: str, messages: list[dict]) -> str:
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages],
                "response_format": {"type": "json_object"}}
        if self.name != "openai":  # some OpenAI reasoning models reject a temperature setting
            body["temperature"] = 0
        r = _post(f"{self.base_url}/chat/completions", body, self._headers(), self.timeout, self.name)
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"{self.name} returned no answer.") from e


class AnthropicProvider:
    name = "anthropic"
    URL = "https://api.anthropic.com/v1"

    def __init__(self, api_key: str, model: str, timeout: float = 120.0):
        self._key, self.model, self.timeout = api_key, model, timeout

    def _headers(self) -> dict:
        return {"x-api-key": self._key, "anthropic-version": "2023-06-01"}

    def status(self) -> dict:
        return {"provider": self.name, "model": self.model, "available": bool(self._key), "detail": "Anthropic key from this browser."}

    def list_models(self) -> list[str]:
        r = _get(f"{self.URL}/models?limit=100", self._headers())
        return [m["id"] for m in r.json().get("data", [])]

    def complete(self, system: str, messages: list[dict]) -> str:
        body = {"model": self.model, "max_tokens": 4096, "system": system + "\nReply with one JSON object only.",
                "messages": messages}
        r = _post(f"{self.URL}/messages", body, self._headers(), self.timeout, "Anthropic")
        try:
            return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        except (KeyError, ValueError) as e:
            raise ProviderError("Anthropic returned no answer.") from e


def _get(url: str, headers: dict) -> httpx.Response:
    try:
        r = httpx.get(url, headers=headers, timeout=15)
    except httpx.HTTPError as e:
        raise ProviderError(f"Could not reach the provider ({type(e).__name__}).") from e
    if r.status_code in (401, 403) or (r.status_code == 400 and "key" in r.text.lower() and "valid" in r.text.lower()):
        raise ProviderError("The provider rejected this key. Check that it was copied completely.")
    if r.status_code >= 400:
        raise ProviderError(f"Provider error {r.status_code}: {r.text[:160]}")
    return r


def _post(url: str, body: dict, headers: dict, timeout: float, who: str) -> httpx.Response:
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        raise ProviderError(f"Could not reach {who} ({type(e).__name__}).") from e
    if r.status_code in (401, 403):
        raise ProviderError(f"{who} rejected the key. Reconnect the AI with a valid key.")
    if r.status_code == 429:
        raise ProviderError(f"{who} rate limit or credit limit reached. Wait a minute, or check your plan.")
    if r.status_code >= 400:
        raise ProviderError(f"{who} error {r.status_code}: {r.text[:200]}")
    return r


# Providers a person can connect from the app with their own key. Keys are never stored on the server.
CATALOG = [
    {"id": "gemini", "label": "Google Gemini", "cost": "Free tier", "key_url": "https://aistudio.google.com/apikey",
     "default_model": "gemini-3.8-flash", "needs_key": True},
    {"id": "groq", "label": "Groq", "cost": "Free tier", "key_url": "https://console.groq.com/keys",
     "default_model": "", "needs_key": True},
    {"id": "openrouter", "label": "OpenRouter (many models)", "cost": "Free and paid models",
     "key_url": "https://openrouter.ai/keys", "default_model": "", "needs_key": True},
    {"id": "openai", "label": "OpenAI", "cost": "Paid per use", "key_url": "https://platform.openai.com/api-keys",
     "default_model": "", "needs_key": True},
    {"id": "anthropic", "label": "Anthropic Claude", "cost": "Paid per use", "key_url": "https://console.anthropic.com/settings/keys",
     "default_model": "", "needs_key": True},
    {"id": "ollama", "label": "Ollama on this computer", "cost": "Free, offline", "key_url": "https://ollama.com/download",
     "default_model": "qwen3:8b", "needs_key": False},
]
_BASES = {"openai": "https://api.openai.com/v1", "groq": "https://api.groq.com/openai/v1", "openrouter": "https://openrouter.ai/api/v1"}
# environment variable names the original TradingAgents reads for these providers
KEY_ENV = {"gemini": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def make_provider(provider: str, key: str = "", model: str = ""):
    """Build a provider from what the person connected in the app. Base URLs are fixed (no user-supplied hosts)."""
    if provider == "gemini":
        return GeminiProvider(model=model or None, api_key=key)
    if provider == "anthropic":
        return AnthropicProvider(key, model or "claude-sonnet-5-5")
    if provider in _BASES:
        return OpenAICompatProvider(provider, _BASES[provider], key, model)
    if provider == "ollama":
        return OllamaProvider(model=model or None)
    raise ProviderError(f"Unknown AI provider {provider!r}.")


def list_models(provider: str, key: str = "") -> list[str]:
    p = make_provider(provider, key)
    if isinstance(p, OllamaProvider):
        st = p.status()
        try:
            return sorted(m["name"] for m in httpx.get(f"{p.base_url}/api/tags", timeout=3).json().get("models", []))
        except Exception as e:  # noqa: BLE001
            raise ProviderError(st["detail"]) from e
    return p.list_models()


def default_provider() -> Provider:
    """PURPLE_AI_PROVIDER=gemini|ollama picks one; otherwise Gemini when GOOGLE_API_KEY is set, else local Ollama."""
    choice = os.environ.get("PURPLE_AI_PROVIDER", "").strip().lower()
    if choice == "ollama" or (choice != "gemini" and not os.environ.get("GOOGLE_API_KEY")):
        return OllamaProvider()
    return GeminiProvider()
