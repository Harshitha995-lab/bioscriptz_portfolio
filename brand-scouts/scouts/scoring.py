"""Step 4: score each candidate topic 0-100 (shown as /10)."""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from statistics import mean

from .common import percentile_ranks
from .llm import LLM
from .playbook import PlaybookProvider
from .topics import Topic

DEFAULT_WEIGHTS = {
    "viral_evidence": 30,
    "breadth": 20,
    "momentum": 10,
    "conversion": 15,
    "brand_match": 15,
    "history": 10,
}

BRAND_SYSTEM = (
    "[TASK:brand]\n"
    "You judge how well a topic fits a creator's brand, using the brand brief provided. "
    "Score 0-100: 90+ is a direct fit with the brief, 50 is adjacent, below 30 conflicts with it "
    "(for example job-seeker tips, hustle hype, vanity metrics). "
    'Return {"score": <0-100>, "reason": "<one sentence>"}.'
)


def momentum_score(name: str, total_plays: int, prev_week: dict) -> float | None:
    """Growth vs last week on a 0-100 scale: same = 50, doubled = 75, quadrupled = 100.
    A topic absent from last week's list counts as emerging (65). With no prior week at all
    there is nothing to compare, so return None and let the weight be redistributed."""
    if not prev_week:
        return None
    prev = {k.lower(): v for k, v in prev_week.items()}.get(name.lower())
    if prev is None:
        return 65.0
    ratio = (total_plays + 1) / (prev + 1)
    return max(0.0, min(100.0, 50 + 25 * math.log2(ratio)))


def conversion_raw(topic: Topic) -> float:
    cta_share = sum(1 for r in topic.reels if r.cta_type not in ("", "none")) / len(topic.reels)
    comment_norm = min(mean(r.comment_ratio for r in topic.reels) / 0.15, 1.0)
    return 0.6 * cta_share + 0.4 * comment_norm


def compute_factors(topics: list[Topic], prev_week: dict, playbook: PlaybookProvider) -> None:
    viral_raw = [mean(sorted((r.heat for r in t.reels), reverse=True)[:3]) for t in topics]
    viral = percentile_ranks(viral_raw)
    breadth = percentile_ranks([len(t.accounts) for t in topics])
    conv = percentile_ranks([conversion_raw(t) for t in topics])
    for t, v, b, c in zip(topics, viral, breadth, conv):
        t.factors.update(
            viral_evidence=v,
            breadth=b,
            conversion=c,
            momentum=momentum_score(t.name, t.total_plays, prev_week),
            history=playbook.history_score(t.name),
        )


def score_brand_match(topics: list[Topic], llm: LLM, brief: str, max_workers: int = 8) -> None:
    """One scorer run per topic, in parallel."""

    def one(t: Topic):
        user = json.dumps(
            {
                "brand_brief": brief,
                "topic": t.name,
                "examples": [{"hook": r.hook, "caption": r.caption[:300], "angle": r.angle} for r in t.reels[:3]],
            }
        )
        try:
            resp = llm.complete_json(BRAND_SYSTEM, user)
            score = max(0.0, min(100.0, float(resp["score"])))
            return score, str(resp.get("reason", ""))
        except Exception as exc:
            return None, f"brand-match scoring failed, weight redistributed: {exc}"

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(one, topics))
    for t, (score, reason) in zip(topics, results):
        t.factors["brand_match"] = score
        t.notes.append(f"Brand match: {reason}")


def combine(weights: dict, factors: dict) -> tuple[float, dict]:
    """Weighted average over the factors that exist. Missing ones (None) give up their weight
    pro rata, so a topic is never punished for data the system does not have yet."""
    present = {k: w for k, w in weights.items() if factors.get(k) is not None}
    total = sum(present.values())
    if total == 0:
        return 0.0, {}
    used = {k: 100.0 * w / total for k, w in present.items()}
    return sum(factors[k] * w for k, w in present.items()) / total, used


def score_topics(topics: list[Topic], weights: dict | None = None) -> list[Topic]:
    weights = weights or DEFAULT_WEIGHTS
    for t in topics:
        t.score, t.weights_used = combine(weights, t.factors)
    return sorted(topics, key=lambda t: t.score, reverse=True)


def cap_topics(topics: list[Topic], max_topics: int | None) -> list[Topic]:
    """Keep the strongest max_topics (by viral evidence and breadth) before the per-topic model calls.
    Needs compute_factors to have run."""
    if max_topics and len(topics) > max_topics:
        topics = sorted(topics, key=lambda t: -(0.6 * t.factors["viral_evidence"] + 0.4 * t.factors["breadth"]))[:max_topics]
    return topics
