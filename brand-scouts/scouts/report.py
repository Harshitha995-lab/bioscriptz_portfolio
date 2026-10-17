"""Write the week's outputs: JSON for machines, Markdown for Harshitha."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .topics import Topic

FACTOR_LABELS = {
    "viral_evidence": "viral evidence",
    "breadth": "breadth",
    "momentum": "momentum",
    "conversion": "conversion",
    "brand_match": "brand match",
    "history": "your history",
}


def render_markdown(topics: list[Topic], date: str, weights: dict, top_n: int, sample: bool) -> str:
    lines = [f"# Instagram winners: week of {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic data and rule-based labelling. Not real Instagram results.", ""]
    lines += [
        "Scores are out of 10 and are **relative to this week's candidates**: the best topic is not "
        "'perfect', it is the best of the batch. Each score shows its factor breakdown and the Reels behind it.",
        "",
    ]
    for rank, t in enumerate(topics[:top_n], start=1):
        flag = "  ⚠️ thin evidence (one account or one Reel)" if t.thin else ""
        lines.append(f"## {rank}. {t.name}: {t.score / 10:.1f}/10{flag}")
        parts = [
            f"{FACTOR_LABELS[k]} {t.factors[k] / 10:.1f}" if t.factors.get(k) is not None else f"{FACTOR_LABELS[k]} n/a"
            for k in FACTOR_LABELS
        ]
        lines.append("- Factors (0-10): " + " · ".join(parts))
        if any(v is None for v in t.factors.values()):
            missing = [FACTOR_LABELS[k] for k, v in t.factors.items() if v is None]
            lines.append(f"- Not scored (weight shared across the rest): {', '.join(missing)}")
        for note in t.notes:
            lines.append(f"- {note}")
        angles = Counter(r.angle for r in t.reels)
        ctas = Counter(r.cta_type for r in t.reels)
        lines.append("- Angles seen: " + ", ".join(f"{a} ×{n}" for a, n in angles.most_common()))
        lines.append("- CTAs seen: " + ", ".join(f"{c} ×{n}" for c, n in ctas.most_common()))
        lines.append(f"- Evidence: {len(t.reels)} Reels from {len(t.accounts)} accounts, {t.total_plays:,} plays in total")
        for r in t.reels[:3]:
            lines.append(
                f"  - [@{r.account}]({r.url}): {r.plays:,} plays · {r.velocity:,.0f}/day · "
                f"{r.reach_ratio:.1f}× its follower count. Hook: “{r.hook}”"
            )
        lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir: Path, date: str, reels, topics: list[Topic], stats: dict, weights: dict, top_n: int, sample: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reels.json").write_text(json.dumps([r.to_dict() for r in reels], indent=2), encoding="utf-8")
    (out_dir / "topics.json").write_text(json.dumps([t.to_dict() for t in topics], indent=2), encoding="utf-8")
    (out_dir / "run_stats.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    (out_dir / "top10.md").write_text(render_markdown(topics, date, weights, top_n, sample), encoding="utf-8")
