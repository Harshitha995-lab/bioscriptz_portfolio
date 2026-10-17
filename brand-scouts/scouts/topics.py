"""Step 3: label each Reel with a topic, then group Reels into candidate topics."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from .common import Reel
from .llm import LLM

DEFAULT_ANGLES = ["story", "contrarian", "proof", "how-to", "authority"]
CTA_TYPES = ["comment-keyword", "dm", "link", "follow", "none"]

def build_label_system(angles: list[str]) -> str:
    return (
        "[TASK:label]\n"
        "You label Instagram Reels for a personal-branding research tool.\n"
        "For each Reel return: relevant (bool), topic, angle, cta_type, hook.\n"
        "- relevant: true only if the Reel teaches or argues something about personal branding, "
        "founder-led content, building an audience, or turning content into leads or sales. "
        "Ads for design or branding services, giveaways and unrelated lifestyle content are not relevant.\n"
        "- topic: a short noun phrase (3-8 words). If the Reel fits a name in known_topics, reuse that "
        "exact name so topic names stay stable week to week.\n"
        f"- angle: one of {angles}.\n"
        f"- cta_type: one of {CTA_TYPES}.\n"
        "- hook: the exact opening line, quoted from the transcript or caption.\n"
        'Return {"labels": [{"id": ..., "relevant": ..., "topic": ..., "angle": ..., "cta_type": ..., "hook": ...}]}.'
    )


@dataclass
class Topic:
    name: str
    reels: list[Reel]
    factors: dict = field(default_factory=dict)  # each 0-100 or None when unavailable
    weights_used: dict = field(default_factory=dict)
    score: float = 0.0                           # 0-100
    notes: list = field(default_factory=list)
    peers: list = field(default_factory=list)    # same-topic Reels that did NOT clear the viral bar (comparison group)

    @property
    def accounts(self) -> set:
        return {r.account for r in self.reels}

    @property
    def total_plays(self) -> int:
        return sum(r.plays for r in self.reels)

    @property
    def thin(self) -> bool:
        """Fewer than 2 Reels or 2 accounts: weak evidence, may be a one-account fluke."""
        return len(self.reels) < 2 or len(self.accounts) < 2

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "score_out_of_10": round(self.score / 10, 1),
            "thin_evidence": self.thin,
            "reel_count": len(self.reels),
            "account_count": len(self.accounts),
            "total_plays": self.total_plays,
            "factors": {k: (None if v is None else round(v, 1)) for k, v in self.factors.items()},
            "weights_used": {k: round(v, 1) for k, v in self.weights_used.items()},
            "notes": self.notes,
            "reels": [r.id for r in self.reels],
        }


def normalize_topic(name: str) -> str:
    name = " ".join(str(name).split()).strip(" .")
    return name[:1].upper() + name[1:] if name else ""


def label_reels(reels: list[Reel], llm: LLM, known_topics=(), batch_size: int = 20, angles=None) -> tuple[list[Reel], dict]:
    angles = list(angles or DEFAULT_ANGLES)
    system = build_label_system(angles)
    stats = {"input": len(reels), "labelled": 0, "irrelevant": 0, "unlabelled": 0, "errors": []}
    labelled: list[Reel] = []
    for i in range(0, len(reels), batch_size):
        batch = reels[i : i + batch_size]
        user = json.dumps(
            {
                "known_topics": list(known_topics),
                "reels": [
                    {"id": r.id, "caption": r.caption[:600], "transcript": r.transcript[:1500]} for r in batch
                ],
            }
        )
        try:
            resp = llm.complete_json(system, user)
        except Exception as exc:  # one bad batch must not lose the whole run; reported in stats
            stats["errors"].append(f"batch {i // batch_size}: {exc}")
            stats["unlabelled"] += len(batch)
            continue
        by_id = {str(x.get("id")): x for x in resp.get("labels", []) if isinstance(x, dict)}
        for r in batch:
            lab = by_id.get(r.id)
            topic = normalize_topic(lab.get("topic", "")) if lab else ""
            if not lab or (lab.get("relevant", False) and not topic):
                stats["unlabelled"] += 1
                continue
            if not lab.get("relevant", False):
                stats["irrelevant"] += 1
                continue
            r.topic = topic
            r.angle = lab.get("angle") if lab.get("angle") in angles else "other"  # unknown angles are not guessed
            r.cta_type = lab.get("cta_type") if lab.get("cta_type") in CTA_TYPES else "none"
            r.hook = str(lab.get("hook", ""))[:300]
            labelled.append(r)
            stats["labelled"] += 1
    return labelled, stats


def group_topics(reels: list[Reel]) -> list[Topic]:
    groups: dict[str, list[Reel]] = {}
    for r in reels:
        groups.setdefault(r.topic.lower(), []).append(r)
    topics = []
    for rs in groups.values():
        name = Counter(r.topic for r in rs).most_common(1)[0][0]
        topics.append(Topic(name=name, reels=sorted(rs, key=lambda r: -r.heat)))
    return topics
