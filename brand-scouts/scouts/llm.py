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
