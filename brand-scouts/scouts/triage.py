"""Step 2: clean the harvest and keep only the outliers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .common import Reel, percentile_ranks, utcnow


@dataclass
class TriageConfig:
    max_age_days: int = 14
    min_plays: int = 5000
    keep_top: int = 300
    spam_terms: list = field(default_factory=list)
    relevance_terms: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "TriageConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def derive_metrics(reel: Reel, now: datetime) -> None:
    # Unknown post date is treated as 7 days old; very new posts are floored at 6 hours
    # so a Reel from this morning does not get an absurd plays-per-day figure.
    age_days = (now - reel.posted_at).total_seconds() / 86400 if reel.posted_at else 7.0
    age_days = max(age_days, 0.25)
    reel.velocity = reel.plays / age_days
    reel.reach_ratio = reel.plays / max(reel.followers or 0, 1000)
    if reel.account_median_plays and reel.account_median_plays > 0:
        reel.outperformance = reel.plays / reel.account_median_plays
    else:
        reel.outperformance = reel.reach_ratio
    reel.comment_ratio = reel.comments / max(reel.likes, 1)


def dedupe(reels: list[Reel]) -> list[Reel]:
    """One entry per Reel id (or url). Keeps the snapshot with the most plays."""
    best: dict[str, Reel] = {}
    for r in reels:
        key = r.id or r.url
        if key not in best or r.plays > best[key].plays:
            best[key] = r
    return list(best.values())


def within_window(reel: Reel, now: datetime, max_age_days: int) -> bool:
    if reel.posted_at is None:
        return True
    age_days = (now - reel.posted_at).total_seconds() / 86400
    return -1 <= age_days <= max_age_days


def is_spam(reel: Reel, terms: list[str]) -> bool:
    text = reel.text.lower()
    return any(t.lower() in text for t in terms)


def looks_relevant(reel: Reel, terms: list[str]) -> bool:
    """Generous keyword pre-filter. The labelling step makes the real relevance call."""
    if not terms:
        return True
    text = reel.text.lower()
    return any(t.lower() in text for t in terms)


def triage(reels: list[Reel], cfg: TriageConfig, now: datetime | None = None) -> tuple[list[Reel], dict]:
    now = now or utcnow()
    stats = {"input": len(reels)}
    reels = dedupe(reels)
    stats["after_dedupe"] = len(reels)
    reels = [r for r in reels if within_window(r, now, cfg.max_age_days)]
    stats["after_window"] = len(reels)
    reels = [r for r in reels if r.plays >= cfg.min_plays]
    stats["after_min_plays"] = len(reels)
    reels = [r for r in reels if not is_spam(r, cfg.spam_terms)]
    stats["after_spam"] = len(reels)
    reels = [r for r in reels if looks_relevant(r, cfg.relevance_terms)]
    stats["after_relevance"] = len(reels)

    for r in reels:
        derive_metrics(r, now)
    vel = percentile_ranks([r.velocity for r in reels])
    out = percentile_ranks([r.outperformance for r in reels])
    for r, v, o in zip(reels, vel, out):
        r.heat = round(0.5 * v + 0.5 * o, 2)
    reels.sort(key=lambda r: r.heat, reverse=True)
    reels = reels[: cfg.keep_top]
    stats["kept"] = len(reels)
    return reels, stats
