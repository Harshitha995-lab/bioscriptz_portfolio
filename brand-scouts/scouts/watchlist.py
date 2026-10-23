"""Competitor watchlist tracking over time.

Each run saves a snapshot of every watched Reel's numbers. That gives each creator a baseline ("usual" plays) that
keeps improving across weeks, flags a new Reel as an outlier when it beats that baseline by a wide margin, and shows
how fast a Reel kept growing between runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from .common import Reel, parse_datetime, utcnow


def append_snapshot(path: Path, reels: list[Reel], when: datetime | None = None) -> int:
    """Append one line per Reel. History is never rewritten, so a bad run can be removed by deleting its lines."""
    when = when or utcnow()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in reels:
            fh.write(json.dumps({"seen": when.isoformat(), "id": r.id, "account": r.account, "url": r.url, "plays": r.plays,
                                 "likes": r.likes, "comments": r.comments,
                                 "posted_at": r.posted_at.isoformat() if r.posted_at else None}) + "\n")
    return len(reels)


def load_history(path: Path) -> dict[str, list[dict]]:
    """{reel id: snapshots oldest first}. Unreadable lines are skipped, not fatal."""
    out: dict[str, list[dict]] = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if not all(k in row for k in ("id", "seen", "plays", "account")):
                continue                      # incomplete line: skip it rather than fail the whole history
            out.setdefault(str(row["id"]), []).append(row)
        except (ValueError, TypeError):
            continue
    for rows in out.values():
        rows.sort(key=lambda r: r["seen"])
    return out


def known_reels(history: dict, reels_now: list[Reel]) -> dict[str, dict]:
    """Latest known numbers per Reel id, from history plus this run (this run wins)."""
    latest = {i: {"account": rows[-1]["account"], "plays": rows[-1]["plays"], "posted_at": parse_datetime(rows[-1].get("posted_at"))}
              for i, rows in history.items()}
    for r in reels_now:
        latest[r.id] = {"account": r.account, "plays": r.plays, "posted_at": r.posted_at}
    return latest


def baselines(known: dict, handles: list[str], min_reels: int = 5, recent: int = 50) -> dict[str, float]:
    """Median plays of an account's most recent Reels. Only for accounts with enough Reels to mean something."""
    out = {}
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for h in handles:
        mine = [v for v in known.values() if v["account"].lower() == h.lower()]
        mine.sort(key=lambda v: v["posted_at"] or epoch, reverse=True)
        plays = [v["plays"] for v in mine[:recent]]
        if len(plays) >= min_reels:
            out[h.lower()] = float(median(plays))
    return out


@dataclass
class WatchRow:
    reel: Reel
    baseline: float
    ratio: float
    growth_per_day: float | None


def growth_per_day(history: dict, reel: Reel) -> float | None:
    rows = history.get(reel.id, [])
    if len(rows) < 2:
        return None
    a, b = parse_datetime(rows[0]["seen"]), parse_datetime(rows[-1]["seen"])
    days = (b - a).total_seconds() / 86400
    return (rows[-1]["plays"] - rows[0]["plays"]) / days if days >= 1 else None


def outlier_feed(reels_now: list[Reel], history: dict, handles: list[str], *, k: float = 3.0, max_age_days: int = 30,
                 min_reels: int = 5, now: datetime | None = None) -> tuple[list[WatchRow], dict, dict]:
    """Recent Reels from watched accounts that beat the account's own baseline by at least k times."""
    now = now or utcnow()
    base = baselines(known_reels(history, reels_now), handles, min_reels)
    watched = {h.lower() for h in handles}
    rows = []
    for r in reels_now:
        b = base.get(r.account.lower())
        if r.account.lower() not in watched or not b:
            continue
        if r.posted_at and (now - r.posted_at).total_seconds() / 86400 > max_age_days:
            continue
        if r.plays / b >= k:
            rows.append(WatchRow(r, b, r.plays / b, growth_per_day(history, r)))
    rows.sort(key=lambda w: -w.ratio)
    seen = {}
    for r in reels_now:
        if r.account.lower() in watched:
            seen.setdefault(r.account.lower(), []).append(r)
    table = {h: {"reels_seen": len(seen.get(h.lower(), [])), "baseline": base.get(h.lower()),
                 "outliers": sum(1 for w in rows if w.reel.account.lower() == h.lower()),
                 "best_ratio": max([w.ratio for w in rows if w.reel.account.lower() == h.lower()], default=None)} for h in handles}
    return rows, table, base
