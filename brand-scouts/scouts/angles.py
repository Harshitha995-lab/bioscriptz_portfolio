"""Step 5: test each top topic against the content angles, then shortlist (with the 80/20 slot)."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from .common import read_lines
from .llm import LLM
from .playbook import PlaybookProvider
from .scoring import combine
from .topics import Topic

ANGLE_WEIGHTS = {"evidence": 35, "baseline": 20, "fit": 30, "history": 15}
SHRINK_K = 2  # a single Reel counts like one vote against two votes for the angle's weekly average

ANGLE_SYSTEM = (
    "[TASK:angles]\n"
    "You turn a winning Instagram topic into content angles for the founder of a personal-branding agency. "
    "For EACH angle in `angles` return: pitch (one sentence: what the Reel would argue or show), "
    "hook (the exact spoken opening line, under 20 words), fit (0-100: how well the angle suits the brand "
    "brief AND feels fresh compared with the example hooks, which show what is already out there), and reason (one sentence). "
    "Never invent statistics, client results or quotes. If an angle needs a real example, write "
    "[add your real example] in the pitch. "
    'Return {"angles": [{"angle": ..., "pitch": ..., "hook": ..., "fit": ..., "reason": ...}]}.'
)


def load_angles(path: Path) -> dict[str, str]:
    """'name: meaning' lines -> {name: meaning}."""
    out = {}
    for line in read_lines(path):
        name, _, meaning = line.partition(":")
        out[name.strip()] = meaning.strip()
    return out


@dataclass
class AngleIdea:
    topic: str
    angle: str
    pitch: str = ""
    hook: str = ""
    fit: float | None = None
    fit_reason: str = ""
    evidence_n: int = 0                  # Reels in this topic that used this angle
    evidence: float | None = None        # their average heat, pulled toward the angle's weekly baseline (= baseline when untested)
    baseline: float | None = None        # average heat of every Reel with this angle this week
    history: float | None = None
    evidence_reels: list = field(default_factory=list)
    score: float = 0.0
    weights_used: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        """'proven' = seen working in this topic this week. 'experiment' = untested here."""
        return "proven" if self.evidence_n > 0 else "experiment"

    def to_dict(self) -> dict:
        return {
            "topic": self.topic, "angle": self.angle, "kind": self.kind,
            "score": round(self.score, 1), "score_out_of_10": round(self.score / 10, 1),
            "pitch": self.pitch, "hook": self.hook, "fit": self.fit, "fit_reason": self.fit_reason,
            "evidence_reels": self.evidence_reels, "evidence_n": self.evidence_n,
            "evidence": None if self.evidence is None else round(self.evidence, 1),
            "baseline": None if self.baseline is None else round(self.baseline, 1),
            "weights_used": {k: round(v, 1) for k, v in self.weights_used.items()},
        }


def angle_baselines(topics: list[Topic]) -> dict[str, float]:
    by_angle: dict[str, list[float]] = {}
    for t in topics:
        for r in t.reels:
            by_angle.setdefault(r.angle, []).append(r.heat)
    return {a: mean(v) for a, v in by_angle.items()}


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def expand_angles(topics: list[Topic], llm: LLM, angles: dict[str, str], brief: str,
                  playbook: PlaybookProvider, baselines: dict[str, float] | None = None,
                  max_workers: int = 8) -> list[AngleIdea]:
    """topics x angles ideas. One ideation call per topic, in parallel."""
    baselines = baselines if baselines is not None else angle_baselines(topics)

    def ideate(t: Topic) -> tuple[dict, str]:
        user = json.dumps({
            "brand_brief": brief,
            "topic": t.name,
            "angles": [{"name": n, "meaning": m} for n, m in angles.items()],
            "examples": [{"hook": r.hook, "angle": r.angle} for r in t.reels[:5]],
        })
        try:
            resp = llm.complete_json(ANGLE_SYSTEM, user)
            return {str(x.get("angle")): x for x in resp.get("angles", []) if isinstance(x, dict)}, ""
        except Exception as exc:
            return {}, f"angle ideation failed: {exc}"

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        ideated = list(pool.map(ideate, topics))

    ideas: list[AngleIdea] = []
    for t, (by_angle, error) in zip(topics, ideated):
        for name in angles:
            x = by_angle.get(name, {})
            rs = [r for r in t.reels if r.angle == name]
            base = baselines.get(name)
            idea = AngleIdea(topic=t.name, angle=name, pitch=str(x.get("pitch", "")), hook=str(x.get("hook", "")),
                             baseline=base, evidence_n=len(rs))
            try:
                idea.fit = _clamp(float(x["fit"]))
            except (KeyError, TypeError, ValueError):
                idea.fit = None
            idea.fit_reason = str(x.get("reason", "")) or error
            # Shrink toward the angle's weekly average. With no Reels (n = 0) this is exactly that average,
            # so an untested angle gets no reward for missing data: it is judged on fit alone, at par on evidence.
            prior = base if base is not None else 50.0
            idea.evidence = (sum(r.heat for r in rs) + SHRINK_K * prior) / (len(rs) + SHRINK_K)
            if rs:
                idea.evidence_reels = [{"url": r.url, "account": r.account, "plays": r.plays} for r in sorted(rs, key=lambda r: -r.heat)[:3]]
            idea.history = playbook.history_score(f"{t.name} / {name}")
            idea.score, idea.weights_used = combine(ANGLE_WEIGHTS, {
                "evidence": idea.evidence, "baseline": idea.baseline, "fit": idea.fit, "history": idea.history})
            ideas.append(idea)
    return ideas


@dataclass
class Pick:
    topic: Topic
    slot: str                 # "data" or "experiment"
    rank_score: float
    angles: list[AngleIdea]

    def to_dict(self) -> dict:
        return {"topic": self.topic.name, "slot": self.slot, "rank_score": round(self.rank_score, 1),
                "topic_score": round(self.topic.score, 1), "angles": [a.to_dict() for a in self.angles]}


def shortlist(topics: list[Topic], ideas: list[AngleIdea], n_topics: int = 5, per_topic: int = 3,
              experiment_slots: int = 1) -> tuple[list[Pick], list[str]]:
    """Data-backed topics first, then the experiment slot(s). Returns (picks, notes)."""
    notes: list[str] = []
    by_topic: dict[str, list[AngleIdea]] = {}
    for i in ideas:
        by_topic.setdefault(i.topic, []).append(i)

    def usable(its: list[AngleIdea]) -> list[AngleIdea]:
        complete = [i for i in its if i.pitch]  # an angle with no pitch/hook is not something to hand over
        return sorted(complete or its, key=lambda i: -i.score)

    ranked = []
    for t in topics:
        its = usable(by_topic.get(t.name, []))
        best = [i.score for i in its[:2]]
        ranked.append((0.6 * t.score + 0.4 * (mean(best) if best else t.score), t, its))
    ranked.sort(key=lambda x: -x[0])

    n = min(n_topics, len(ranked))
    exp = min(experiment_slots, max(n - 1, 0))   # always keep at least one data-backed pick
    if exp < experiment_slots:
        notes.append(f"Only {len(ranked)} topics available, so {exp} of {experiment_slots} experiment slot(s) could be filled.")
    data_n = n - exp

    picks = [Pick(t, "data", rank, its[:per_topic]) for rank, t, its in ranked[:data_n]]
    remaining = ranked[data_n:]

    for _ in range(exp):
        candidates = []
        for rank, t, its in remaining:
            untested = [i for i in its if i.kind == "experiment"]
            if untested:
                candidates.append((max(i.score for i in untested), rank, t, its))
            elif t.thin:
                candidates.append((its[0].score if its else 0.0, rank, t, its))
        if not candidates:
            notes.append("No untested angle or thin-evidence topic was left for the experiment slot, so it went to the "
                         "next-best data-backed topic. This week's list has no experiment in it.")
            if remaining:
                rank, t, its = remaining.pop(0)
                picks.append(Pick(t, "data", rank, its[:per_topic]))
            continue
        _, rank, t, its = max(candidates, key=lambda c: c[0])
        remaining = [r for r in remaining if r[1] is not t]
        # untested angles first, so the experiment is actually an experiment
        chosen = sorted(its, key=lambda i: (i.kind != "experiment", -i.score))[:per_topic]
        picks.append(Pick(t, "experiment", rank, chosen))
    return picks, notes
