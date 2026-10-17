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


def render_shortlist(picks, notes: list[str], date: str, sample: bool, experiment_slots: int) -> str:
    lines = [f"# Instagram shortlist: week of {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic data, rule-based labelling and placeholder angle text. Not real results.", ""]
    lines += [
        "How this was chosen: the top topics by score were each tested against the content angles, using how that "
        "angle performed in the topic this week, how it performs across all topics this week, and a fit check "
        "against your brand brief. Most picks are data-backed; "
        f"{experiment_slots} slot(s) are reserved for an experiment, so the list does not only repeat what has already worked. "
        "**You make the final call.**",
        "",
    ]
    for n in notes:
        lines += [f"> Note: {n}", ""]
    for i, p in enumerate(picks, start=1):
        label = "DATA-BACKED" if p.slot == "data" else "EXPERIMENT"
        thin = " ⚠️ thin evidence" if p.topic.thin else ""
        lines.append(f"## {i}. {p.topic.name} [{label}]: topic score {p.topic.score / 10:.1f}/10{thin}")
        lines.append(f"{len(p.topic.reels)} Reels from {len(p.topic.accounts)} accounts, {p.topic.total_plays:,} plays in total.")
        lines.append("")
        for a in p.angles:
            seen = f"proven: {a.evidence_n} Reel(s) this week" if a.kind == "proven" else "UNTESTED in this topic this week (experiment)"
            lines.append(f"### {a.angle}: {a.score / 10:.1f}/10 ({seen})")
            lines.append(f"- Pitch: {a.pitch or '(none generated)'}")
            lines.append(f"- Hook: “{a.hook}”" if a.hook else "- Hook: (none generated)")
            fit = f"{a.fit:.0f}" if a.fit is not None else "n/a"
            lines.append(f"- Fit with your brand: {fit}. {a.fit_reason}")
            for e in a.evidence_reels:
                lines.append(f"- Evidence: [@{e['account']}]({e['url']}), {e['plays']:,} plays")
            lines.append("")
    return "\n".join(lines)


def _hook_line(bd) -> str:
    parts = []
    for ch, label, key in (("audio", "audio", "text"), ("text", "on-screen text", "text"), ("video", "visual", "description")):
        h = bd.hooks[ch]
        if not h["analysed"]:
            parts.append(f"{label}: not analysed")
        elif h["type"] == "none":
            parts.append(f"{label}: none")
        else:
            body = h.get(key) or ""
            warn = " ⚠️ not found verbatim in transcript" if ch == "audio" and body and not h["verified_quote"] else ""
            parts.append(f"{label}: “{body}” ({h['type']}){warn}" if body else f"{label}: {h['type']}")
    return " · ".join(parts)


def render_viral_analysis(va, topics: list, reels_by_id: dict, date: str, sample: bool) -> str:
    from .viral_analysis import describe_feature

    cov = va.coverage
    lines = [f"# Viral analysis: why Reels on the same topic travelled further. Week of {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic Reels, text-only rule-based analysis, no video frames. The numbers below show the "
                  "format of the report, not anything real about Instagram.", ""]
    lines += [
        "**How to read this.** Each Reel's presentation (hooks, format, story loop, spice, CTA) was described by the analyst "
        "*without seeing its view count*. The comparisons below were then computed in code, between viral Reels and non-viral Reels "
        "on the **same topic**. This shows what viral Reels did differently *in this sample*. It is correlation, not proof, and small "
        "samples throw up patterns by chance. `q` corrects for testing many features at once, so trust “likely real” most.",
        "",
        f"**Coverage:** {cov['reels_analysed']} Reels analysed ({cov['failed']} failed), {cov['with_frames']} with video frames. "
        f"Hooks analysed: audio {cov['audio_hook_analysed']}, on-screen text {cov['text_hook_analysed']}, visual {cov['video_hook_analysed']}.",
    ]
    if cov["with_frames"] == 0:
        lines.append("> Video and on-screen-text hooks, format, tone and pacing were **not analysed**: no video frames were available "
                     "(they need a video URL from the scraper and ffmpeg). Only the audio hook, story loop, spice, CTA and structure are covered.")
    if cov["unverified_audio_quotes"]:
        lines.append(f"> {cov['unverified_audio_quotes']} audio-hook quote(s) could not be found word for word in the transcript; they are marked ⚠️.")
    for e in cov["errors"]:
        lines.append(f"> Error: {e}")
    lines.append("")

    lines += [f"## Across all topics: what separates the winners", f"Comparison: {va.pooled_basis}. Group sizes: {va.pooled_n[0]} vs {va.pooled_n[1]}.", ""]
    if va.pooled:
        lines += ["| Feature | Viral | Not viral | Gap | Read |", "|---|---|---|---|---|"]
        for c in va.pooled[:12]:
            lines.append(f"| {describe_feature(c.feature)} | {c.viral_yes}/{c.viral_n} | {c.rest_yes}/{c.rest_n} | {c.gap:+.0%} | {c.read} |")
    else:
        lines.append("No feature separated the groups by enough to report. That is a real result, not a failure: with this sample, "
                     "presentation did not clearly differ.")
    lines.append("")

    by_name = {t.name: t for t in topics}
    for i, ta in enumerate(va.topics, start=1):
        t = by_name[ta.topic]
        lines += [f"## {i}. {ta.topic}",
                  f"Compared: {ta.basis}" + (f" ({len(ta.viral_ids)} vs {len(ta.rest_ids)})." if ta.rest_ids else f" ({len(ta.viral_ids)} viral Reels described below)."), ""]
        if ta.rest_ids and not ta.contrasts and not ta.error:
            lines += ["No feature separated the viral Reels from the rest by enough to report for this topic.", ""]
        ex = ta.explanation
        if ta.error:
            lines.append(f"> {ta.error}")
        if ex:
            lines.append(ex.get("summary", ""))
            for key, title in (("what_to_copy", "Worth copying"), ("what_not_to_copy", "Not worth copying")):
                if ex.get(key):
                    lines.append(f"**{title}:** " + "; ".join(describe_feature(x) for x in ex[key]))
            if ex.get("template"):
                lines += ["", "**Template to adapt (fill the [brackets] from your own experience):**", "", f"> {ex['template']}"]
            for cav in ex.get("caveats", []):
                lines.append(f"- Caveat: {cav}")
            lines.append("")
        if ta.contrasts:
            lines += ["| Feature | Viral | Not viral | Gap | Read |", "|---|---|---|---|---|"]
            for c in ta.contrasts[:8]:
                lines.append(f"| {describe_feature(c.feature)} | {c.viral_yes}/{c.viral_n} | {c.rest_yes}/{c.rest_n} | {c.gap:+.0%} | {c.read} |")
            lines.append("")
        positive = {c.feature for c in ta.contrasts if c.gap > 0 and c.read != "weak"}
        for rid in ta.viral_ids[:3]:
            bd, r = va.breakdowns[rid], reels_by_id[rid]
            f = va.features.get(rid, {})
            lines.append(f"**[@{r.account}]({r.url})**: {r.plays:,} plays, {r.reach_ratio:.1f}× its follower count")
            lines.append(f"- Hooks: {_hook_line(bd)}")
            loop = bd.loop
            lines.append(f"- Format: {bd.format} · Loop: {loop['type']}" + (f" (opens: “{loop['open_loop']}”)" if loop.get("open_loop") else "")
                         + (f" · Re-hook: “{loop['re_hook']}”" if loop.get("re_hook") else ""))
            lines.append(f"- Structure: " + " → ".join(b["beat"] for b in bd.structure))
            lines.append(f"- Spice: {', '.join(bd.spice) or 'none'} · CTA: {bd.cta['type']}")
            standouts = [describe_feature(x) for x in sorted(positive) if f.get(x)]
            if standouts:
                lines.append(f"- Shares features linked to reach in this topic: {'; '.join(standouts)}")
            lines.append("")
    return "\n".join(lines)
