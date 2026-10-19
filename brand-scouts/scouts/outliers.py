"""Step 2: find viral outliers in the vault, with no new scraping.

Two tiers, because the evidence differs:
  - "own usual": the creator has at least 5 Reels in the vault, and this one beat their median by k times. Strong.
  - "followers": we only know the creator's size, so the Reel is judged by plays against followers. Weaker: a small account
    can spike for reasons that say nothing about the content.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

from .common import Reel, utcnow


@dataclass
class Outlier:
    reel: Reel
    ratio: float
    basis: str                 # "own usual" or "followers"
    usual: float | None
    velocity: float

    @property
    def strong(self) -> bool:
        return self.basis == "own usual"


def account_usuals(reels: list[Reel], min_reels: int = 5) -> dict[str, float]:
    """Median plays per account over every Reel we hold for it, regardless of niche or date. Unknown accounts are never pooled."""
    plays: dict[str, list[int]] = {}
    for r in reels:
        if r.account and r.account != "unknown":
            plays.setdefault(r.account.lower(), []).append(r.plays)
    return {a: float(median(p)) for a, p in plays.items() if len(p) >= min_reels}


def find_outliers(reels: list[Reel], *, niche: str | None = None, days: int = 30, min_plays: int = 1000, k_usual: float = 3.0,
                  k_followers: float = 5.0, min_reels: int = 5, now: datetime | None = None) -> tuple[list[Outlier], dict]:
    now = now or utcnow()
    usuals = account_usuals(reels, min_reels)             # computed on everything, so the baseline is not biased by the filters below
    out, considered = [], 0
    for r in reels:
        if niche and r.niche.lower() != niche.lower():
            continue
        if r.posted_at and (now - r.posted_at).total_seconds() / 86400 > days:
            continue
        if r.plays < min_plays:
            continue
        considered += 1
        age = max((now - r.posted_at).total_seconds() / 86400, 0.25) if r.posted_at else 7.0
        usual = usuals.get(r.account.lower())
        if usual:
            ratio, basis = r.plays / usual, "own usual"
            if ratio < k_usual:
                continue
        elif r.followers:
            ratio, basis = r.plays / max(r.followers, 1000), "followers"
            if ratio < k_followers:
                continue
        else:
            continue
        out.append(Outlier(r, ratio, basis, usual, r.plays / age))
    out.sort(key=lambda o: (not o.strong, -o.ratio))
    stats = {"reels_in_vault": len(reels), "considered": considered, "creators_with_a_usual": len(usuals),
             "outliers": len(out), "strong": sum(o.strong for o in out)}
    return out, stats
