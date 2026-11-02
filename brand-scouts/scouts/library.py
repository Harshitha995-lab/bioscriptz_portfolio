"""The viral Reel library: ~100 winning Reels spread across keywords, each with its full transcript, a breakdown
of how it is built, and, where the same creator made an earlier weaker version of the same topic, a direct
comparison of the two ('twins')."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import comb

from .common import Reel
from .llm import LLM
from .viral_analysis import ViralBreakdown, benjamini_hochberg, brief_reel, describe_feature


# ------------------------------------------------------------------ selection across keywords

def select_library(reels: list[Reel], n: int = 100, per_keyword_cap: int = 5, per_account_cap: int = 2) -> tuple[list[Reel], dict]:
    """Best Reels first, but taken round-robin across keywords so no keyword (or creator) fills the list.
    A Reel with no known keyword is grouped by its topic instead."""
    groups: dict[str, list[Reel]] = {}
    for r in sorted(reels, key=lambda r: -r.heat):
        groups.setdefault((r.keyword or r.topic or "(unknown)").lower(), []).append(r)
    picked, per_account, taken = [], {}, {k: 0 for k in groups}
    progressed = True
    while len(picked) < n and progressed:
        progressed = False
        for key in sorted(groups, key=lambda k: -groups[k][0].heat if groups[k] else 0):
            if len(picked) >= n:
                break
            while groups[key] and taken[key] < per_keyword_cap:
                r = groups[key].pop(0)
                if per_account.get(r.account.lower(), 0) >= per_account_cap and r.account != "unknown":
                    continue
                picked.append(r)
                per_account[r.account.lower()] = per_account.get(r.account.lower(), 0) + 1
                taken[key] += 1
                progressed = True
                break
    keywords = {(r.keyword or r.topic or "(unknown)").lower() for r in picked}
    return picked, {"selected": len(picked), "requested": n, "keywords_covered": len(keywords), "keywords_available": len(groups),
                    "per_keyword_cap": per_keyword_cap, "per_account_cap": per_account_cap}


# ------------------------------------------------------------------ twins

@dataclass
class TwinPair:
    account: str
    topic: str
    winner: Reel
    baseline: Reel

    @property
    def ratio(self) -> float:
        return self.winner.plays / max(self.baseline.plays, 1)

    @property
    def baseline_came_first(self) -> bool | None:
        a, b = self.baseline.posted_at, self.winner.posted_at
        return None if a is None or b is None else a < b


def find_twins(reels: list[Reel], winners: list[Reel], min_ratio: float = 10.0, min_baseline_plays: int = 1000) -> list[TwinPair]:
    """For each winner, the same creator's best attempt at the SAME topic that fell short by at least min_ratio.
    The closest miss is used, because that is the fairest 'before' picture."""
    by_key: dict[tuple, list[Reel]] = {}
    for r in reels:
        if r.topic:
            by_key.setdefault((r.account.lower(), r.topic.lower()), []).append(r)
    pairs = []
    for w in winners:
        if not w.topic or w.account == "unknown":
            continue
        cands = [r for r in by_key.get((w.account.lower(), w.topic.lower()), [])
                 if r.id != w.id and r.plays >= min_baseline_plays and r.plays * min_ratio <= w.plays]
        if cands:
            pairs.append(TwinPair(w.account, w.topic, w, max(cands, key=lambda r: r.plays)))
    return pairs


def feature_changes(winner: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """Yes/no features the winner gained or lost. Only features known for both Reels count."""
    added = sorted(k for k, v in winner.items() if v is True and baseline.get(k) is False)
    dropped = sorted(k for k, v in baseline.items() if v is True and winner.get(k) is False)
    return added, dropped


def sign_test_p(a: int, b: int) -> float:
    """Two-sided exact sign test: of a+b pairs that changed, did a go one way by more than chance (50/50)?"""
    d = a + b
    if d == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(d, i) for i in range(0, min(a, b) + 1)) / 2 ** d)


@dataclass
class PairPattern:
    feature: str
    added: int
    dropped: int
    p: float
    q: float = 1.0

    @property
    def read(self) -> str:
        if self.q < 0.10:
            return "likely real"
        if self.p < 0.05:
            return "possible (may be luck)"
        return "weak"

    def to_dict(self) -> dict:
        return {"feature": self.feature, "winner_added_in": self.added, "winner_dropped_in": self.dropped,
                "p": round(self.p, 4), "q": round(self.q, 4), "read": self.read}


def pair_patterns(changes: list[tuple[list[str], list[str]]], min_changed: int = 3) -> list[PairPattern]:
    """Across all twin pairs: which changes keep showing up in the same direction?"""
    feats = {f for added, dropped in changes for f in added + dropped}
    rows = []
    for f in feats:
        a = sum(f in added for added, _ in changes)
        b = sum(f in dropped for _, dropped in changes)
        if a + b >= min_changed:
            rows.append(PairPattern(f, a, b, sign_test_p(a, b)))
    for row, q in zip(rows, benjamini_hochberg([r.p for r in rows])):
        row.q = q
    return sorted(rows, key=lambda r: (r.p, -(r.added + r.dropped)))


PAIR_SYSTEM = (
    "[TASK:explain_pair]\n"
    "You are given two Instagram Reels by the SAME creator on the SAME topic. One reached far more people. You get the "
    "presentation features that changed between them (computed in code) and descriptions of both. Explain what the "
    "winning version did differently, for someone who wants to replicate it.\n"
    "Rules: use only the listed changes and descriptions. One pair cannot prove cause: timing, the algorithm, a trending "
    "sound, the posting time and audience mood also affect reach and cannot be seen here, so say that plainly. Never invent "
    "statistics, results or quotes. In `template`, write a fill-in-the-blank skeleton using [brackets] for what the "
    "creator must supply from their own experience; do not copy anyone's wording. "
    'Return {"what_changed": ..., "worth_testing": [...], "template": ..., "caveats": [...]}.'
)


def explain_pair(pair: TwinPair, bd_win: ViralBreakdown, bd_base: ViralBreakdown, added: list[str], dropped: list[str],
                 llm: LLM, brief: str) -> dict:
    user = json.dumps({
        "brand_brief": brief, "topic": pair.topic,
        "winner": brief_reel(pair.winner, bd_win), "earlier_or_weaker_version": brief_reel(pair.baseline, bd_base),
        "winner_added": [describe_feature(f) for f in added], "winner_dropped": [describe_feature(f) for f in dropped],
        "baseline_came_first": pair.baseline_came_first,
    })
    try:
        return llm.complete_json(PAIR_SYSTEM, user)
    except Exception as exc:
        return {"error": f"explanation failed: {exc}"}


# ------------------------------------------------------------------ assembling the library

@dataclass
class LibraryResult:
    reels: list
    selection: dict
    breakdowns: dict
    features: dict
    twins: list = field(default_factory=list)       # dicts: pair, added, dropped, explanation, note
    patterns: list = field(default_factory=list)
    transcripts: dict = field(default_factory=dict)
    followups: dict = field(default_factory=dict)
    prevalence: list = field(default_factory=list)


def _unique(reels: list[Reel]) -> list[Reel]:
    seen, out = set(), []
    for r in reels:
        if r.id not in seen:
            seen.add(r.id)
            out.append(r)
    return out


def prevalence(features: dict, ids: list[str], min_n: int = 10, top: int = 10) -> list[tuple]:
    counts: dict[str, list[int]] = {}
    for i in ids:
        for k, v in features.get(i, {}).items():
            c = counts.setdefault(k, [0, 0])
            c[0] += bool(v)
            c[1] += 1
    rows = [(k, yes, n) for k, (yes, n) in counts.items() if n >= min_n]
    return sorted(rows, key=lambda r: (-r[1] / r[2], r[0]))[:top]


def run_library(labelled: list[Reel], extra_pool: list[Reel], llm: LLM, vocab: dict, brief: str, angles: list[str], cfg: dict, *,
                followups_loader=None, transcriber=None, frames=None, breakdowns: dict | None = None) -> LibraryResult:
    from .topics import label_reels
    from .transcribe import ensure_transcripts
    from .triage import dedupe
    from .viral_analysis import analyse_reels, build_features

    library, selection = select_library(labelled, cfg["n"], cfg["per_keyword_cap"], cfg["per_account_cap"])
    follow = {"fetched": 0, "labelled": 0, "matched": 0, "error": ""}
    matched: list[Reel] = []
    if cfg.get("twin_search", True) and followups_loader and library:
        known = {r.id for r in labelled} | {r.id for r in extra_pool}
        try:
            fetched = followups_loader(sorted({r.account for r in library if r.account != "unknown"}))
        except Exception as exc:
            fetched, follow["error"] = [], f"follow-up fetch failed: {exc}"
        fetched = [r for r in dedupe(fetched) if r.id not in known and r.plays >= cfg["twin_min_baseline_plays"]]
        per_account: dict[str, int] = {}
        capped = []
        for r in sorted(fetched, key=lambda r: -r.plays):       # nearest misses first
            if per_account.get(r.account.lower(), 0) < cfg.get("followup_per_account", 15):
                per_account[r.account.lower()] = per_account.get(r.account.lower(), 0) + 1
                capped.append(r)
        follow["fetched"] = len(capped)
        got, lstats = label_reels(capped, llm, sorted({r.topic for r in library}), angles=angles)
        wanted = {(r.account.lower(), r.topic.lower()) for r in library}
        matched = [r for r in got if (r.account.lower(), r.topic.lower()) in wanted]
        follow.update(labelled=len(got), matched=len(matched))
        if lstats["errors"]:
            follow["error"] = "; ".join(lstats["errors"][:2])

    pool = _unique(list(labelled) + list(extra_pool) + matched)
    twins = find_twins(pool, library, cfg["twin_min_ratio"], cfg["twin_min_baseline_plays"])
    to_describe = _unique(library + [t.baseline for t in twins])
    transcripts = ensure_transcripts(to_describe, transcriber, cfg.get("max_transcriptions", 150)) if cfg.get("transcribe_missing", True) else {}

    breakdowns = dict(breakdowns or {})
    breakdowns.update(analyse_reels([r for r in to_describe if r.id not in breakdowns], llm, vocab, frames))
    features = {r.id: build_features(r, breakdowns[r.id], vocab) for r in to_describe if not breakdowns[r.id].error}

    twin_rows, all_changes, counted_accounts = [], [], set()
    for t in sorted(twins, key=lambda t: -t.ratio):
        bw, bb = breakdowns[t.winner.id], breakdowns[t.baseline.id]
        row = {"pair": t, "added": [], "dropped": [], "explanation": {}, "note": ""}
        if bw.error or bb.error:
            row["note"] = "One of the two Reels could not be analysed."
        else:
            row["added"], row["dropped"] = feature_changes(features[t.winner.id], features[t.baseline.id])
            if t.account.lower() not in counted_accounts:      # one pair per creator in the statistics: a creator's pairs are not independent
                counted_accounts.add(t.account.lower())
                all_changes.append((row["added"], row["dropped"]))
            if row["added"] or row["dropped"]:
                row["explanation"] = explain_pair(t, bw, bb, row["added"], row["dropped"], llm, brief)
            else:
                row["note"] = "No difference in the presentation features we could see. The gap may come from timing, sound, or luck."
        twin_rows.append(row)
    patterns = pair_patterns(all_changes, cfg.get("min_pairs_for_pattern", 3))
    selection["min_keywords_needed"] = -(-cfg["n"] // cfg["per_keyword_cap"])
    selection["pairs_in_statistics"] = len(counted_accounts)
    return LibraryResult(library, selection, breakdowns, features, twin_rows, patterns, transcripts, follow,
                         prevalence(features, [r.id for r in library]))
