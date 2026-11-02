"""Step 3: transcripts, hook deconstruction, and the winning content format.

For each creator whose outlier we analyse, we also analyse some of THEIR OWN ordinary Reels. Pooling those pairs, matched per
creator, shows what outliers do differently from the same people's normal output: same audience, same voice, so bigger
accounts cannot explain the difference. Analysis is blind to performance numbers (see viral_analysis.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .common import Reel
from .frameworks import Evidence, load_frameworks, scoreboard
from .library import prevalence
from .llm import LLM
from .outliers import Outlier
from .transcribe import ensure_transcripts
from .vault import Vault
from .viral_analysis import Contrast, ViralBreakdown, analyse_reels, build_features, contrasts, spread


@dataclass
class FormatsResult:
    outliers: list
    breakdowns: dict
    features: dict
    pooled_out: list = field(default_factory=list)
    pooled_norm: list = field(default_factory=list)
    contrasts: list = field(default_factory=list)
    board: list = field(default_factory=list)
    prevalence: list = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    basis: str = "each creator's outliers vs their own ordinary Reels, matched per creator"


def pick_normals(account_reels: list[Reel], outlier_ids: set, usual: float, n: int) -> list[Reel]:
    """Ordinary Reels from the same creator: not outliers, and not far above their usual. Spread across the range."""
    normals = [r for r in account_reels if r.id not in outlier_ids and r.plays <= usual * 1.5]
    return spread(sorted(normals, key=lambda r: -r.plays), n)


def analyse_outliers(vault: Vault, outliers: list[Outlier], llm: LLM, vocab: dict, *, frames=None, transcriber=None, top: int = 20,
                     normals_per_creator: int = 3, min_group: int = 3, min_gap: float = 0.25, max_transcriptions: int = 100,
                     frameworks: list[dict] | None = None) -> FormatsResult:
    strong = [o for o in outliers if o.strong][:top]
    weak = [o for o in outliers if not o.strong][: max(top - len(strong), 0)]
    chosen = strong + weak
    by_account: dict[str, list[Reel]] = {}
    for r in vault.reels():
        by_account.setdefault(r.account.lower(), []).append(r)
    outlier_ids = {o.reel.id for o in outliers}

    normals: dict[str, list[Reel]] = {}
    for o in strong:
        a = o.reel.account.lower()
        if a not in normals:
            normals[a] = pick_normals(by_account.get(a, []), outlier_ids, o.usual, normals_per_creator)

    targets = {o.reel.id: o.reel for o in chosen}
    for rs in normals.values():
        targets.update({r.id: r for r in rs})
    tstats = ensure_transcripts(list(targets.values()), transcriber, max_transcriptions)
    for r in targets.values():
        if r.transcript:
            vault.set_transcript(r.id, r.transcript)

    cached = vault.breakdowns(list(targets))
    fresh = analyse_reels([r for i, r in targets.items() if i not in cached], llm, vocab, frames)
    for bd in fresh.values():
        vault.save_breakdown(bd)
    breakdowns = {**cached, **fresh}
    ok = {i: b for i, b in breakdowns.items() if not b.error}
    feats = {i: build_features(targets[i], b, vocab) for i, b in ok.items()}

    pool_out, pool_norm, pairs = [], [], []
    for a, norm in normals.items():
        mine = [o.reel for o in strong if o.reel.account.lower() == a and o.reel.id in ok]
        norm = [r for r in norm if r.id in ok]
        k = min(len(mine), len(norm))
        if k:
            pool_out += mine[:k]
            pool_norm += norm[:k]
            pairs.append((feats[mine[0].id], feats[norm[0].id]))      # one pair per creator for the sign test
    cons = contrasts([feats[r.id] for r in pool_out], [feats[r.id] for r in pool_norm], min_group, min_gap) if pool_out else []

    out_feats = [feats[o.reel.id] for o in chosen if o.reel.id in feats]
    board = scoreboard(frameworks or load_frameworks(), out_feats, [feats[r.id] for r in pool_out], [feats[r.id] for r in pool_norm],
                       pairs, min_group=min_group)
    count = lambda ch: sum(1 for b in ok.values() if b.hooks[ch]["analysed"])
    cov = {"outliers_analysed": sum(o.reel.id in ok for o in chosen), "ordinary_reels_analysed": sum(r.id in ok for rs in normals.values() for r in rs),
           "creators_compared": len(pairs), "pooled": [len(pool_out), len(pool_norm)], "failed": len(breakdowns) - len(ok),
           "with_frames": sum("frames" in b.evidence for b in ok.values()), "audio_hook_analysed": count("audio"),
           "text_hook_analysed": count("text"), "video_hook_analysed": count("video"), "transcripts": tstats,
           "errors": [b.error for b in breakdowns.values() if b.error][:5],
           "weak_basis_outliers": len(weak)}
    vault.set_meta("framework_board", [{"id": e.fw["id"], "level": e.level, "reasons": e.reasons} for e in board])
    return FormatsResult(chosen, breakdowns, feats, pool_out, pool_norm, cons, board, prevalence(feats, [o.reel.id for o in chosen]), cov)


def load_board(vault: Vault, frameworks: list[dict] | None = None) -> list[Evidence]:
    """The framework ratings from the last `analyse`, or an all-'thin' board when none exists yet (the script then says so)."""
    frameworks = frameworks or load_frameworks()
    saved = {row["id"]: row for row in vault.get_meta("framework_board", [])}
    return [Evidence(fw, level=saved.get(fw["id"], {}).get("level", "thin"),
                     reasons=saved.get(fw["id"], {}).get("reasons", ["no analysis has been run yet; run `agent.py analyse` first"])) for fw in frameworks]
