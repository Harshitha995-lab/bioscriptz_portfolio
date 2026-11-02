"""Viral analysis: why did some Reels on a topic travel further than others on the SAME topic?

1. Describe how each Reel is built (three hook channels, format, story loop, spice, CTA). The analyst is
   deliberately NOT shown view counts, so it cannot rationalise a success after the fact.
2. Compare viral Reels with non-viral Reels on the same topic using plain statistics, in code.
3. Only then ask the model to explain the numbers, with strict rules against claiming more than they show.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from math import comb
from pathlib import Path

from .common import ROOT, Reel, load_json
from .llm import LLM
from .topics import Topic

VOCAB_PATH = ROOT / "config" / "viral_vocab.json"


def load_vocab(path: Path = VOCAB_PATH) -> dict:
    return load_json(path)


# ------------------------------------------------------------------ 1. describe each Reel

ANALYST_SYSTEM = (
    "[TASK:breakdown]\n"
    "You decode how ONE Instagram Reel is built, so someone can learn from it. You are deliberately not told how "
    "the Reel performed; do not guess or comment on its success.\n"
    "Evidence you may be given: transcript (spoken words), caption, and frames (images sampled from the video; "
    "frame_times_s gives the second of each, and the earliest frames cover the opening 3 seconds). Judge only from "
    "what is provided. If a field cannot be judged from the evidence, leave it empty instead of guessing.\n"
    "Definitions: audio hook = the first spoken sentence. text hook = on-screen text visible in the first 3 seconds. "
    "video hook = what is shown or happens visually in the first 3 seconds. spice = devices added on top of a plain "
    "version of the topic. loop = the open question or tension the Reel creates, and where it pays off.\n"
    "Quote text exactly as given; never invent numbers, names, results or quotes. Use only words from `vocab`.\n"
    'Return {"hooks": {"audio": {"text": ..., "type": ...}, "text": {"text": ..., "type": ...}, '
    '"video": {"description": ..., "type": ...}}, "hooks_aligned": true|false|null, "format": ..., '
    '"style": {"tone": ..., "pacing": ...}, "structure": [{"beat": ..., "summary": ...}], '
    '"loop": {"type": ..., "open_loop": ..., "payoff": ..., "re_hook": ...|null}, "spice": [...], '
    '"cta": {"type": ..., "text": ...}}. hooks_aligned = true when every hook you could see makes the same promise.'
)


def _norm(s) -> str:
    return " ".join(str(s).lower().split())


def quote_in(text: str, source: str) -> bool:
    """Is `text` a verbatim excerpt of `source` (ignoring case, spacing and edge punctuation)?"""
    t = _norm(text).strip(" .\"'“”…")
    return bool(t) and t in _norm(source)


def _pick(value, options, default):
    v = str(value or "").strip().lower()
    return v if v in options else default


@dataclass
class ViralBreakdown:
    reel_id: str
    hooks: dict = field(default_factory=dict)
    hooks_aligned: bool | None = None
    format: str = "unknown"
    style: dict = field(default_factory=dict)
    structure: list = field(default_factory=list)
    loop: dict = field(default_factory=dict)
    spice: list = field(default_factory=list)
    cta: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)   # which of transcript / caption / frames were available
    error: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def normalize_breakdown(raw: dict, reel: Reel, vocab: dict, n_frames: int) -> ViralBreakdown:
    """Validate the model's answer against the vocabulary AND against the evidence that really existed.
    Claims about things it could not have seen are discarded, whatever the model said."""
    has_frames = n_frames > 0
    h = raw.get("hooks") or {}
    a_raw, t_raw, v_raw = (h.get("audio") or {}), (h.get("text") or {}), (h.get("video") or {})

    audio = {"analysed": bool(reel.transcript), "text": "", "type": "unknown", "verified_quote": False}
    if audio["analysed"]:
        a_text = str(a_raw.get("text", "")).strip()
        audio.update(text=a_text, type=_pick(a_raw.get("type"), vocab["hook_types"], "other"),
                     verified_quote=quote_in(a_text, reel.transcript))
    text = {"analysed": has_frames, "text": "", "type": "unknown"}
    video = {"analysed": has_frames, "description": "", "type": "unknown"}
    if has_frames:
        text.update(text=str(t_raw.get("text", "")).strip(), type=_pick(t_raw.get("type"), vocab["hook_types"], "other"))
        video.update(description=str(v_raw.get("description", "")).strip(),
                     type=_pick(v_raw.get("type"), vocab["visual_hook_types"], "other"))

    channels = [c for c in (audio, text, video) if c["analysed"] and c["type"] != "none"]
    aligned = raw.get("hooks_aligned")
    aligned = aligned if isinstance(aligned, bool) and len(channels) >= 2 else None

    style_raw = raw.get("style") or {}
    style = {"tone": _pick(style_raw.get("tone"), vocab["tones"], "unknown") if has_frames else "unknown",
             "pacing": _pick(style_raw.get("pacing"), vocab["pacing"], "unknown") if has_frames else "unknown"}
    loop_raw = raw.get("loop") or {}
    loop = {"type": _pick(loop_raw.get("type"), vocab["loop_types"], "none"),
            "open_loop": str(loop_raw.get("open_loop") or ""), "payoff": str(loop_raw.get("payoff") or ""),
            "re_hook": (str(loop_raw["re_hook"]) if loop_raw.get("re_hook") else None)}
    blocked = set(vocab.get("spice_needs_frames", [])) if not has_frames else set()
    spice = []
    for x in raw.get("spice") or []:
        x = str(x).strip().lower()
        if x in vocab["spice"] and x not in blocked and x not in spice:
            spice.append(x)
    cta_raw = raw.get("cta") or {}
    structure = [{"beat": _pick(b.get("beat"), vocab["beats"], "point"), "summary": str(b.get("summary", ""))[:240]}
                 for b in (raw.get("structure") or [])[:10] if isinstance(b, dict)]
    return ViralBreakdown(
        reel_id=reel.id,
        hooks={"audio": audio, "text": text, "video": video},
        hooks_aligned=aligned,
        format=_pick(raw.get("format"), vocab["formats"], "other") if has_frames else "unknown",
        style=style, structure=structure, loop=loop, spice=spice,
        cta={"type": _pick(cta_raw.get("type"), vocab["cta_types"], "none"), "text": str(cta_raw.get("text", ""))},
        evidence=[e for e, ok in (("transcript", reel.transcript), ("caption", reel.caption), ("frames", has_frames)) if ok],
    )


def analyse_reel(reel: Reel, llm: LLM, vocab: dict, frames_provider=None) -> ViralBreakdown:
    try:
        frames = frames_provider.frames_for(reel) if frames_provider else None
        images = frames.images if frames else []
        # NOTE: no plays, likes, comments or follower counts go into this request.
        user = json.dumps({
            "vocab": {k: v for k, v in vocab.items() if not k.startswith("_")},
            "reel": {"id": reel.id, "caption": reel.caption[:800], "transcript": reel.transcript[:3000],
                     "duration_s": reel.duration_s, "frame_times_s": frames.times if frames else []},
        })
        raw = llm.complete_json(ANALYST_SYSTEM, user, images=images) if images else llm.complete_json(ANALYST_SYSTEM, user)
        return normalize_breakdown(raw, reel, vocab, len(images))
    except Exception as exc:  # reported, never silently dropped
        return ViralBreakdown(reel_id=reel.id, error=f"analysis failed: {exc}")


def analyse_reels(reels: list[Reel], llm: LLM, vocab: dict, frames_provider=None, max_workers: int = 6) -> dict[str, ViralBreakdown]:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda r: analyse_reel(r, llm, vocab, frames_provider), reels))
    return {bd.reel_id: bd for bd in results}


# ------------------------------------------------------------------ 2. compare, in code

def build_features(reel: Reel, bd: ViralBreakdown, vocab: dict) -> dict[str, bool]:
    """Yes/no facts about a Reel's presentation. A feature is present only when the evidence could answer it,
    so 'unknown' never counts as 'no'."""
    f: dict[str, bool] = {}
    if bd.error or not bd.hooks:
        return f
    used = {}
    for ch in ("audio", "text", "video"):
        hk = bd.hooks[ch]
        if not hk["analysed"]:
            continue
        used[ch] = hk["type"] != "none"
        f[f"hook_{ch}"] = used[ch]
        options = vocab["visual_hook_types"] if ch == "video" else vocab["hook_types"]
        if hk["type"] in options or hk["type"] == "other":
            for o in options:
                if o != "none":
                    f[f"hook_{ch}_type:{o}"] = hk["type"] == o
    if len(used) == 3:
        f["all_three_hooks"] = all(used.values())
        f["two_plus_hooks"] = sum(used.values()) >= 2
    if bd.hooks_aligned is not None:
        f["hooks_aligned"] = bd.hooks_aligned
    if bd.format != "unknown":
        for o in vocab["formats"]:
            f[f"format:{o}"] = bd.format == o
    for dim, options in (("tone", vocab["tones"]), ("pacing", vocab["pacing"])):
        if bd.style.get(dim, "unknown") != "unknown":
            for o in options:
                f[f"{dim}:{o}"] = bd.style[dim] == o
    for o in vocab["loop_types"]:
        f[f"loop:{o}"] = bd.loop["type"] == o
    if bd.loop["type"] != "none":
        f["re_hook"] = bool(bd.loop.get("re_hook"))
    skip = set(vocab.get("spice_needs_frames", [])) if "frames" not in bd.evidence else set()
    for o in vocab["spice"]:
        if o not in skip:
            f[f"spice:{o}"] = o in bd.spice
    f["spice_2plus"] = len(bd.spice) >= 2
    f["spice_3plus"] = len(bd.spice) >= 3
    for o in vocab["cta_types"]:
        f[f"cta:{o}"] = bd.cta["type"] == o
    if reel.duration_s:
        d = reel.duration_s
        for name, ok in (("len:under15s", d < 15), ("len:15to30s", 15 <= d < 30), ("len:30to60s", 30 <= d < 60), ("len:60s+", d >= 60)):
            f[name] = ok
    return f


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]] (a/b = viral yes/no, c/d = non-viral yes/no)."""
    n1, n2, k = a + b, c + d, a + c
    total = n1 + n2
    if total == 0:
        return 1.0
    denom = comb(total, k)
    prob = lambda x: comb(n1, x) * comb(n2, k - x) / denom
    observed = prob(a)
    return min(1.0, sum(prob(x) for x in range(max(0, k - n2), min(k, n1) + 1) if prob(x) <= observed * (1 + 1e-9)))


def benjamini_hochberg(ps: list[float]) -> list[float]:
    """Adjusted p-values (q) controlling the false-discovery rate, returned in the input order."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    q, running = [0.0] * m, 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, ps[i] * m / rank)
        q[i] = running
    return q


@dataclass
class Contrast:
    feature: str
    viral_yes: int
    viral_n: int
    rest_yes: int
    rest_n: int
    p: float
    q: float = 1.0

    @property
    def viral_share(self) -> float:
        return self.viral_yes / self.viral_n

    @property
    def rest_share(self) -> float:
        return self.rest_yes / self.rest_n

    @property
    def gap(self) -> float:
        return self.viral_share - self.rest_share

    @property
    def read(self) -> str:
        """q corrects for having tested many features at once; without it some 'patterns' are pure luck."""
        if self.q < 0.10:
            return "likely real"
        if self.p < 0.05:
            return "possible (may be luck)"
        return "weak"

    def to_dict(self) -> dict:
        return {"feature": self.feature, "viral": f"{self.viral_yes}/{self.viral_n}", "non_viral": f"{self.rest_yes}/{self.rest_n}",
                "gap": round(self.gap, 2), "p": round(self.p, 4), "q": round(self.q, 4), "read": self.read}


def contrasts(viral: list[dict], rest: list[dict], min_group: int = 3, min_gap: float = 0.25) -> list[Contrast]:
    names = set().union(*(set(f) for f in viral + rest)) if (viral or rest) else set()
    tested = []
    for name in names:
        v = [f[name] for f in viral if name in f]
        r = [f[name] for f in rest if name in f]
        if len(v) < min_group or len(r) < min_group:
            continue
        a, c = sum(v), sum(r)
        tested.append(Contrast(name, a, len(v), c, len(r), fisher_exact(a, len(v) - a, c, len(r) - c)))
    # adjust p for the number of features tested, so luck across many features is not mistaken for a pattern
    for c, q in zip(tested, benjamini_hochberg([c.p for c in tested])):
        c.q = q
    return sorted((c for c in tested if abs(c.gap) >= min_gap), key=lambda c: (c.p, -abs(c.gap)))


def split_groups(topic: Topic, have: set, min_group: int = 3) -> tuple[list[Reel], list[Reel], str]:
    """Viral vs non-viral on the same topic; if there are no usable non-viral peers, the top vs bottom of the viral set."""
    viral = [r for r in topic.reels if r.id in have]
    peers = [r for r in topic.peers if r.id in have]
    if len(viral) >= min_group and len(peers) >= min_group:
        return viral, peers, "viral Reels vs non-viral Reels on the same topic"
    viral.sort(key=lambda r: -r.heat)
    n = len(viral)
    if n >= 6:
        return viral[: n // 3], viral[-(n // 3):], "top third vs bottom third of the viral Reels (no non-viral peers available)"
    if n >= 4:
        return viral[: n // 2], viral[n // 2:], "top half vs bottom half of the viral Reels (no non-viral peers available)"
    return viral, [], "no comparison possible: too few Reels on this topic"


# ------------------------------------------------------------------ 3. explain the numbers

EXPLAIN_SYSTEM = (
    "[TASK:explain]\n"
    "You explain why some Instagram Reels on one topic travelled further than others on the same topic, for the "
    "founder of a personal-branding agency who wants to replicate what works. You are given statistical contrasts "
    "(computed in code) and descriptions of the Reels.\n"
    "Rules: use only the contrasts and descriptions provided. This is correlation in a small sample, so say 'in this "
    "sample' and never 'causes'. Give most weight to contrasts marked 'likely real', mention 'possible' ones with "
    "that caveat, ignore 'weak' ones. If there are no usable contrasts, say so plainly instead of inventing reasons. "
    "Never invent statistics, results or quotes. In `template`, write a fill-in-the-blank skeleton "
    "(audio hook, on-screen text hook, video hook, beats, payoff, CTA) using [brackets] for the parts the creator "
    "must supply from their own experience; do not copy any creator's wording. "
    'Return {"summary": ..., "what_to_copy": [...], "what_not_to_copy": [...], "template": ..., "caveats": [...]}.'
)


def brief_reel(reel: Reel, bd: ViralBreakdown) -> dict:
    return {"hooks": {k: (v.get("text") or v.get("description") or v["type"]) for k, v in bd.hooks.items() if v.get("analysed")},
            "format": bd.format, "loop": bd.loop.get("type"), "open_loop": bd.loop.get("open_loop"), "spice": bd.spice,
            "cta": bd.cta.get("type"), "structure": [b["beat"] for b in bd.structure]}


@dataclass
class TopicAnalysis:
    topic: str
    basis: str
    viral_ids: list
    rest_ids: list
    contrasts: list
    explanation: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {"topic": self.topic, "basis": self.basis, "viral_reels": self.viral_ids, "comparison_reels": self.rest_ids,
                "contrasts": [c.to_dict() for c in self.contrasts], "explanation": self.explanation, "error": self.error}


@dataclass
class ViralAnalysis:
    breakdowns: dict
    features: dict
    topics: list
    pooled_basis: str
    pooled_n: tuple
    pooled: list
    coverage: dict
    pooled_ids: tuple = ((), ())      # (viral ids, comparison ids) behind `pooled`


def spread(items: list, k: int) -> list:
    """k items evenly spaced through a ranked list, so the sample covers the whole range, not just its top."""
    if len(items) <= k:
        return list(items)
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def select_targets(topic: Topic, viral_n: int, peers_n: int) -> list[Reel]:
    viral = sorted(topic.reels, key=lambda r: -r.heat)[:viral_n]
    peers = spread(sorted(topic.peers, key=lambda r: -r.heat), peers_n)
    return viral + peers


def analyse_topics(topics: list[Topic], llm: LLM, vocab: dict, brief: str, frames_provider=None, *,
                   viral_per_topic: int = 6, peers_per_topic: int = 6, max_reels: int = 120,
                   min_group: int = 3, min_gap: float = 0.25) -> ViralAnalysis:
    targets: dict[str, Reel] = {}
    for t in topics:
        for r in select_targets(t, viral_per_topic, peers_per_topic):
            if len(targets) < max_reels:
                targets.setdefault(r.id, r)
    breakdowns = analyse_reels(list(targets.values()), llm, vocab, frames_provider)
    ok = {i: bd for i, bd in breakdowns.items() if not bd.error}
    features = {i: build_features(targets[i], bd, vocab) for i, bd in ok.items()}
    have = set(ok)

    results = []
    for t in topics:
        v, r, basis = split_groups(t, have, min_group)
        cons = contrasts([features[x.id] for x in v], [features[x.id] for x in r], min_group, min_gap) if v and r else []
        ta = TopicAnalysis(t.name, basis, [x.id for x in v], [x.id for x in r], cons)
        if v and cons:     # nothing to explain without a contrast; don't ask the model to make something up
            examples = {"viral": [brief_reel(x, ok[x.id]) for x in v[:3]], "comparison": [brief_reel(x, ok[x.id]) for x in r[:2]]}
            user = json.dumps({"brand_brief": brief, "topic": t.name, "comparison_basis": basis,
                               "group_sizes": [len(v), len(r)], "contrasts": [c.to_dict() for c in cons], "examples": examples})
            try:
                ta.explanation = llm.complete_json(EXPLAIN_SYSTEM, user)
            except Exception as exc:
                ta.error = f"explanation failed: {exc}"
        results.append(ta)

    # Pooled view across topics. Matched per topic (k viral + k non-viral from each topic) so that one topic with
    # many Reels cannot dominate and turn a topic effect into a fake presentation effect.
    pool_v, pool_r = [], []
    for t in topics:
        v = sorted([x for x in t.reels if x.id in have], key=lambda x: -x.heat)
        pr = sorted([x for x in t.peers if x.id in have], key=lambda x: -x.heat)
        k = min(len(v), len(pr))
        if k:
            pool_v += v[:k]
            pool_r += spread(pr, k)
    pool_basis = "viral vs non-viral Reels on the same topic, matched per topic and pooled across topics"
    if len(pool_v) < min_group:   # no usable non-viral peers anywhere: pool the within-viral splits instead
        by_id = {r.id: r for r in topics_reels(topics)}
        pool_v, pool_r = [], []
        for ta in results:
            if ta.rest_ids:
                pool_v += [by_id[i] for i in ta.viral_ids]
                pool_r += [by_id[i] for i in ta.rest_ids]
        pool_basis = "top vs bottom of the viral Reels within each topic (no non-viral peers were available)"
    pooled = contrasts([features[x.id] for x in pool_v], [features[x.id] for x in pool_r], min_group, min_gap) if pool_v and pool_r else []

    def count(ch):
        return sum(1 for bd in ok.values() if bd.hooks[ch]["analysed"])
    coverage = {"reels_analysed": len(ok), "failed": len(breakdowns) - len(ok), "with_frames": sum("frames" in bd.evidence for bd in ok.values()),
                "audio_hook_analysed": count("audio"), "text_hook_analysed": count("text"), "video_hook_analysed": count("video"),
                "unverified_audio_quotes": sum(1 for bd in ok.values() if bd.hooks["audio"]["analysed"] and not bd.hooks["audio"]["verified_quote"]),
                "errors": [bd.error for bd in breakdowns.values() if bd.error][:5]}
    return ViralAnalysis(breakdowns, features, results, pool_basis, (len(pool_v), len(pool_r)), pooled, coverage,
                         ([r.id for r in pool_v], [r.id for r in pool_r]))


def topics_reels(topics: list[Topic]) -> list[Reel]:
    return [r for t in topics for r in t.reels + t.peers]


FEATURE_NAMES = {
    "hook_audio": "Has an audio hook (spoken opening)", "hook_text": "Has an on-screen text hook", "hook_video": "Has a visual hook",
    "all_three_hooks": "Stacks all three hooks (audio + text + video)", "two_plus_hooks": "Stacks two or more hooks",
    "hooks_aligned": "Hooks make the same promise", "re_hook": "Re-hooks the viewer mid-video",
    "spice_2plus": "Uses 2+ spice devices", "spice_3plus": "Uses 3+ spice devices",
}


def describe_feature(name: str) -> str:
    if name in FEATURE_NAMES:
        return FEATURE_NAMES[name]
    kind, _, value = name.partition(":")
    label = {"hook_audio_type": "Audio hook type", "hook_text_type": "Text hook type", "hook_video_type": "Visual hook type",
             "format": "Format", "tone": "Tone", "pacing": "Pacing", "loop": "Story loop", "spice": "Spice", "cta": "CTA", "len": "Length"}.get(kind)
    return f"{label}: {value}" if label else name
