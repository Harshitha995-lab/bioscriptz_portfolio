"""Storytelling frameworks, rated by the evidence in this week's data rather than by reputation."""
from __future__ import annotations

from dataclasses import dataclass, field

from .common import ROOT, load_json
from .library import sign_test_p
from .viral_analysis import benjamini_hochberg, fisher_exact

LEVEL_RANK = {"supported": 4, "suggestive": 3, "thin": 2, "mixed": 1, "common-to-both": 0, "not-favoured": 0}
STRONG = ("supported", "suggestive")


def load_frameworks(path=ROOT / "config" / "frameworks.json") -> list[dict]:
    return load_json(path)["frameworks"]


def uses(fw: dict, features: dict) -> bool:
    return any(features.get(k) is True for k in fw["match_any"])


@dataclass
class Evidence:
    fw: dict
    n_library: int = 0
    library_total: int = 0
    viral_yes: int = 0
    viral_n: int = 0
    peer_yes: int = 0
    peer_n: int = 0
    p: float | None = None
    q: float | None = None
    pairs_added: int = 0
    pairs_dropped: int = 0
    level: str = "thin"
    reasons: list = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.n_library / self.library_total if self.library_total else 0.0

    def to_dict(self) -> dict:
        return {"id": self.fw["id"], "name": self.fw["name"], "level": self.level, "reasons": self.reasons,
                "winners_using_it": f"{self.n_library}/{self.library_total}",
                "viral_vs_non_viral": f"{self.viral_yes}/{self.viral_n} vs {self.peer_yes}/{self.peer_n}" if self.peer_n else None,
                "p": None if self.p is None else round(self.p, 4), "q": None if self.q is None else round(self.q, 4),
                "pairs_added": self.pairs_added, "pairs_dropped": self.pairs_dropped}


def scoreboard(frameworks: list[dict], library_features: list[dict], viral_features: list[dict], peer_features: list[dict],
               pair_features: list[tuple[dict, dict]], *, min_group: int = 3) -> list[Evidence]:
    """Rate each framework on three kinds of evidence, strongest first:
    1. winners vs non-winners on the same topics, 2. the same creator's winner vs their weaker version, 3. how many winners use it.
    A framework that non-winners use just as often is marked 'common-to-both': it is not what makes Reels win."""
    rows = []
    for fw in frameworks:
        e = Evidence(fw, n_library=sum(uses(fw, f) for f in library_features), library_total=len(library_features))
        e.viral_yes, e.viral_n = sum(uses(fw, f) for f in viral_features), len(viral_features)
        e.peer_yes, e.peer_n = sum(uses(fw, f) for f in peer_features), len(peer_features)
        if e.viral_n >= min_group and e.peer_n >= min_group:
            e.p = fisher_exact(e.viral_yes, e.viral_n - e.viral_yes, e.peer_yes, e.peer_n - e.peer_yes)
        for w, b in pair_features:
            uw, ub = uses(fw, w), uses(fw, b)
            e.pairs_added += uw and not ub
            e.pairs_dropped += ub and not uw
        rows.append(e)
    with_p = [e for e in rows if e.p is not None]
    for e, q in zip(with_p, benjamini_hochberg([e.p for e in with_p])):
        e.q = q

    for e in rows:
        viral_share = e.viral_yes / e.viral_n if e.viral_n else None
        peer_share = e.peer_yes / e.peer_n if e.peer_n else None
        pair_p = sign_test_p(e.pairs_added, e.pairs_dropped)
        has_matched = viral_share is not None and peer_share is not None and (e.viral_yes + e.peer_yes) > 0
        # Two independent kinds of evidence can point the same way, opposite ways, or be missing.
        pos_matched = has_matched and viral_share > peer_share + 0.05
        neg_matched = has_matched and viral_share <= peer_share + 0.05
        pos_pairs = e.pairs_added >= 3 and e.pairs_added > e.pairs_dropped
        neg_pairs = e.pairs_dropped >= 3 and e.pairs_dropped >= e.pairs_added
        matched_text = f"{e.viral_yes}/{e.viral_n} winners vs {e.peer_yes}/{e.peer_n} non-winners on the same topics"
        pair_text = f"creators added it in {e.pairs_added} winning re-makes and dropped it in {e.pairs_dropped}"

        if (pos_matched and neg_pairs) or (pos_pairs and neg_matched):
            e.level = "mixed"
            e.reasons += [f"the evidence disagrees: {matched_text}; {pair_text}"]
        elif neg_matched:
            e.level = "common-to-both"
            e.reasons.append(f"non-winners use it about as often ({matched_text}), so it does not set winners apart")
        elif neg_pairs:
            e.level = "not-favoured"
            e.reasons.append(f"winners tended to drop it ({pair_text})")
        elif (e.q is not None and e.q < 0.10 and pos_matched) or (pos_pairs and pair_p < 0.05):
            e.level = "supported"
            if e.q is not None and e.q < 0.10 and pos_matched:
                e.reasons.append(f"winners use it more ({matched_text}; corrected p {e.q:.3f})")
            if pos_pairs and pair_p < 0.05:
                e.reasons.append(pair_text)
        elif (e.p is not None and e.p < 0.05 and pos_matched) or pos_pairs or (e.n_library >= 5 and e.share >= 0.25):
            e.level = "suggestive"
            if e.p is not None and e.p < 0.05 and pos_matched:
                e.reasons.append(f"winners use it more ({matched_text}), but that may be luck once many frameworks are compared")
            if pos_pairs:
                e.reasons.append(f"{pair_text} (too few pairs to rule out chance)")
            if e.n_library >= 5 and e.share >= 0.25:
                e.reasons.append(f"used by {e.n_library} of {e.library_total} winners (common among winners; not compared with non-winners)")
        else:
            e.level = "thin"
            e.reasons.append(f"seen in only {e.n_library} of {e.library_total} winners; no usable comparison")
    return sorted(rows, key=lambda e: (-LEVEL_RANK[e.level], -e.share))


def pick_framework(board: list[Evidence], angle: str, used: dict, *, experiment: bool = False, cap: int = 2) -> Evidence | None:
    """Evidence first, angle second, variety third.
    - Data-backed slots take the best-evidenced framework, but no framework is used more than `cap` times a week.
    - The experiment slot deliberately takes an untested ('thin' or 'mixed') framework, so the week tests something new.
    - Frameworks rated common-to-both or not-favoured are only used when nothing else exists."""
    usable = [e for e in board if e.level not in ("common-to-both", "not-favoured")] or board
    if not usable:
        return None
    pool = ([e for e in usable if e.level in ("thin", "mixed")] or usable) if experiment else usable
    fresh = [e for e in pool if used.get(e.fw["id"], 0) < cap] or pool
    return min(fresh, key=lambda e: (-LEVEL_RANK[e.level], angle not in e.fw.get("angles", []), used.get(e.fw["id"], 0)))
