"""LLM access. Anything with complete_json(system, user) -> dict works, so tests use a fake."""
from __future__ import annotations

import json
import os
import re
from typing import Protocol


class LLM(Protocol):
    def complete_json(self, system: str, user: str, images: list[bytes] | None = None) -> dict: ...


def parse_json(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating code fences and surrounding prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(text[start : end + 1])


class AnthropicLLM:
    """Needs `pip install anthropic` and ANTHROPIC_API_KEY. Model comes from ANTHROPIC_MODEL."""

    def __init__(self, model: str | None = None, max_tokens: int = 4096):
        import anthropic  # imported lazily so the rest of the project runs without it

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens

    def complete_json(self, system: str, user: str, images: list[bytes] | None = None) -> dict:
        """images: JPEG bytes, sent before the text. Only passed when frames exist."""
        import base64

        content: list = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(img).decode()}}
            for img in (images or [])
        ]
        content.append({"type": "text", "text": user})
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system + "\n\nRespond with a single JSON object and nothing else.",
            messages=[{"role": "user", "content": content if images else user}],
        )
        return parse_json("".join(b.text for b in msg.content if b.type == "text"))


def model_for(task: str, settings: dict | None = None) -> str:
    """Model for a task ('analysis' or 'scripts'): ANTHROPIC_MODEL_<TASK> env, then settings.json "models", then ANTHROPIC_MODEL, then the default."""
    return (os.environ.get(f"ANTHROPIC_MODEL_{task.upper()}") or ((settings or {}).get("models") or {}).get(task)
            or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5")


class GeminiLLM:
    """Google Gemini through the google-genai package (pip install google-genai), for use on Google's free tier.

    The free tier has strict per-minute and per-day limits, so calls are spaced out, run two at a time at most, and retried with
    a pause when Google answers 'too many requests' or 'unavailable'. Model names change: set GEMINI_MODEL in .env to a model
    your Google AI Studio account lists. Not tested against the real service in this project."""

    RETRY_PAUSES = (5, 20, 60)

    def __init__(self, model: str | None = None, api_key: str | None = None, min_interval: float = 4.0, sleep=None, max_tokens: int = 4096):
        import threading
        import time

        from google import genai  # imported lazily so the rest of the project runs without it

        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=key)
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.max_tokens = max_tokens
        self.min_interval, self._sleep, self._clock = min_interval, sleep or time.sleep, time.monotonic
        self._gate, self._pace, self._last = threading.Semaphore(2), threading.Lock(), 0.0

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        text = f"{type(exc).__name__} {exc}".lower()
        return any(s in text for s in ("429", "resource_exhausted", "503", "unavailable", "overloaded", "deadline", "timeout"))

    def _space_out(self) -> None:
        with self._pace:
            wait = self._last + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()

    def complete_json(self, system: str, user: str, images: list[bytes] | None = None) -> dict:
        from google.genai import types

        parts = [types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in (images or [])] + [user]
        config = types.GenerateContentConfig(system_instruction=system + "\n\nRespond with a single JSON object and nothing else.",
                                             response_mime_type="application/json", max_output_tokens=self.max_tokens)
        last: Exception | None = None
        for attempt in range(len(self.RETRY_PAUSES) + 1):
            with self._gate:
                self._space_out()
                try:
                    resp = self.client.models.generate_content(model=self.model, contents=parts, config=config)
                    return parse_json(resp.text or "")
                except Exception as exc:
                    last = exc
                    if not self._retryable(exc) or attempt == len(self.RETRY_PAUSES):
                        raise
            self._sleep(self.RETRY_PAUSES[attempt])
        raise last  # pragma: no cover


PROVIDERS = ("anthropic", "gemini")


def provider() -> str:
    p = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
    if p not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)} (got '{p}').")
    return p


def key_name(p: str | None = None) -> str:
    return "GEMINI_API_KEY" if (p or provider()) == "gemini" else "ANTHROPIC_API_KEY"


def make_llm(task: str, settings: dict | None = None, spec: str | None = None):
    """The model client for a task. `spec` ('gemini:<model>' or '<claude model>') overrides LLM_PROVIDER, used by compare-models."""
    if spec:
        p, _, name = spec.partition(":") if spec.split(":")[0] in PROVIDERS else ("anthropic", "", spec)
    else:
        p, name = provider(), None
    if p == "gemini":
        return GeminiLLM(name or None)
    return AnthropicLLM(name or model_for(task, settings))
