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
    def complete_json(self, system: str, user: str, images=None) -> dict:
        data = json.loads(user)
        if "[TASK:label]" in system:
            return {"labels": [self._label(r) for r in data["reels"]]}
        if "[TASK:brand]" in system:
            for pattern, name, score, reason in TOPIC_RULES:
                if name == data["topic"]:
                    return {"score": score, "reason": reason}
            return {"score": 40, "reason": "No rule for this topic."}
        if "[TASK:angles]" in system:
            return {"angles": [self._angle(data["topic"], a["name"]) for a in data["angles"]]}
        if "[TASK:breakdown]" in system:
            return self._breakdown(data["reel"], bool(images))
        if "[TASK:explain_pair]" in system:
            ch = data["winner_added"]
            return {"what_changed": f"[sample] The winning version added: {', '.join(ch) or 'nothing we can see'}.",
                    "worth_testing": ch[:3], "template": "[sample] Audio hook: [...] / On-screen text: [...] / CTA: [...]",
                    "caveats": ["Sample data; rule-based text, not a real analysis.", "One pair cannot prove cause."]}
        if "[TASK:explain]" in system:
            return self._explain(data)
        raise ValueError("unknown task")

    # (topic, angle) -> fit. Anything not listed gets a middling 55. Sample data only.
    FIT = {
        ("Content that converts into leads", "proof"): 92,
        ("Content that converts into leads", "how-to"): 90,
        ("Trust beats content volume", "authority"): 91,
        ("Trust beats content volume", "story"): 84,
        ("Personal branding feels cringe", "contrarian"): 88,
        ("Founder origin stories", "story"): 93,
        ("Founder origin stories", "authority"): 80,
        ("Systems over daily posting", "how-to"): 72,
    }

    def _angle(self, topic: str, angle: str) -> dict:
        return {"angle": angle, "pitch": f"[sample] The {angle} angle on '{topic}'.",
                "hook": f"[sample hook] {topic}: the {angle} version.",
                "fit": self.FIT.get((topic, angle), 55), "reason": "Sample rule-based fit, not a real judgement."}

    def _breakdown(self, reel: dict, has_frames: bool) -> dict:
        """Crude text rules over the transcript. Sample mode and tests only; a real model does this properly."""
        tr = reel["transcript"] or reel["caption"]
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", tr.strip()) if s]
        first = sentences[0] if sentences else ""
        low = tr.lower()
        htype = ("question" if first.endswith("?") else "contrarian" if re.search(r"\b(stop|never|wrong|actually)\b", first, re.I)
                 else "number-list" if re.search(r"\d|\bthree\b|ways", first, re.I) else "confession" if re.search(r"\b(i|my)\b", first, re.I)
                 else "bold-claim")
        loop = ("countdown-list" if re.search(r"\bways\b|\bsteps?\b|\bthree\b", low) else "myth-bust" if re.search(r"myth|wrong|stop", low)
                else "curiosity-gap" if "?" in tr or "here is" in low else "none")
        spice = [s for s, hit in (("specific-number", re.search(r"\d", tr)), ("personal-stake", re.search(r"\b(i|my)\b", low)),
                                  ("controversy", re.search(r"cringe|wrong|stop", low))) if hit]
        cta = "comment-keyword" if re.search(r"(?i:comment) [A-Z]{3,}", tr) else "dm" if re.search(r"\bdm\b", low) else "none"
        beats = [{"beat": "hook", "summary": first}] + [{"beat": "point", "summary": s} for s in sentences[1:-1]]
        if len(sentences) > 1:
            beats.append({"beat": "cta" if cta != "none" else "payoff", "summary": sentences[-1]})
        out = {"hooks": {"audio": {"text": first, "type": htype}, "text": {"text": "", "type": "none"},
                         "video": {"description": "", "type": "none"}},
               "hooks_aligned": None, "format": "talking-head", "style": {"tone": "raw", "pacing": "fast"},
               "structure": beats, "loop": {"type": loop, "open_loop": first if loop != "none" else "", "payoff": sentences[-1] if sentences else "",
                                            "re_hook": None}, "spice": spice, "cta": {"type": cta, "text": sentences[-1] if cta != "none" else ""}}
        return out

    def _explain(self, data: dict) -> dict:
        usable = [c for c in data["contrasts"] if c["read"] != "weak"]
        if not usable:
            return {"summary": "[sample] No contrast was strong enough to explain; in this sample the viral Reels did not clearly differ in presentation.",
                    "what_to_copy": [], "what_not_to_copy": [], "template": "[sample] none", "caveats": ["Sample data; rule-based text, not a real analysis."]}
        top = usable[0]
        return {"summary": f"[sample] In this sample, '{top['feature']}' was more common among viral Reels ({top['viral']} vs {top['non_viral']}).",
                "what_to_copy": [c["feature"] for c in usable if c["gap"] > 0][:3], "what_not_to_copy": [c["feature"] for c in usable if c["gap"] < 0][:3],
                "template": "[sample] Audio hook: [your opening line] / On-screen text: [...] / Visual: [...] / Beats: [...] / CTA: [...]",
                "caveats": ["Sample data; rule-based text, not a real analysis."]}

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
