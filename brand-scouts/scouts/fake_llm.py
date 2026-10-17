"""Rule-based stand-in for the LLM so the pipeline runs offline: sample mode and tests.
It is NOT a quality judge. It only follows simple keyword rules over the synthetic sample data."""
from __future__ import annotations

import json
import re

# Patterns carry their own case flags: (?i:...) is case-insensitive, the rest is case-sensitive.
TOPIC_RULES = [
    (r"(?i:cringe)", "Personal branding feels cringe", 82, "Debate topic that fits founder-brand positioning."),
    (r"(?i:\btrust\b)", "Trust beats content volume", 90, "Core to the founder-led, trust-first pitch."),
    (r"(?i:origin)", "Founder origin stories", 86, "Storytelling is a core lens."),
    (r"(?i:lead magnet|funnel)|(?i:comment) [A-Z]{3,}", "Content that converts into leads", 95, "Directly about conversion, the agency's core claim."),
    (r"\bAI\b", "AI-assisted content workflows", 55, "Adjacent; relevant only if tied to founder voice."),
    (r"(?i:system|consisten)", "Systems over daily posting", 70, "Useful but generic unless tied to founders."),
]
IRRELEVANT = ("logo design", "giveaway", "workout")


class FakeLLM:
    def complete_json(self, system: str, user: str) -> dict:
        data = json.loads(user)
        if "[TASK:label]" in system:
            return {"labels": [self._label(r) for r in data["reels"]]}
        if "[TASK:brand]" in system:
            for pattern, name, score, reason in TOPIC_RULES:
                if name == data["topic"]:
                    return {"score": score, "reason": reason}
            return {"score": 40, "reason": "No rule for this topic."}
        raise ValueError("unknown task")

    def _label(self, reel: dict) -> dict:
        text = f"{reel['caption']}\n{reel['transcript']}"
        if any(w in text.lower() for w in IRRELEVANT):
            return {"id": reel["id"], "relevant": False}
        topic = next((name for pattern, name, _, _ in TOPIC_RULES if re.search(pattern, text)), None)
        if topic is None:
            return {"id": reel["id"], "relevant": False}
        cta = "comment-keyword" if re.search(r"(?i:comment) [A-Z]{3,}", text) else "dm" if re.search(r"\bdm me\b", text, re.I) else "link" if "link in bio" in text.lower() else "none"
        low = text.lower()
        angle = (
            "contrarian" if re.search(r"stop|myth|wrong|actually", low)
            else "how-to" if re.search(r"step|how to|framework", low)
            else "proof" if re.search(r"revenue|clients|result", low)
            else "story" if re.search(r"story|origin", low)
            else "authority"
        )
        hook = re.split(r"(?<=[.!?])\s", (reel["transcript"] or reel["caption"]).strip())[0]
        return {"id": reel["id"], "relevant": True, "topic": topic, "angle": angle, "cta_type": cta, "hook": hook}
