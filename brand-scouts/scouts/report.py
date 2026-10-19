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


def _n(x: int) -> str:
    return f"{x:,}"


def render_library(res, date: str, sample: bool) -> str:
    from .viral_analysis import describe_feature

    sel, tr, fu = res.selection, res.transcripts, res.followups
    lines = [f"# Viral Reel library: week of {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic Reels, rule-based text analysis, no video frames. This shows the format of the report, "
                  "not anything real about Instagram.", ""]
    lines += [
        f"**{sel['selected']} viral Reels** (asked for {sel['requested']}) covering {sel['keywords_covered']} of {sel['keywords_available']} keywords, "
        f"at most {sel['per_keyword_cap']} per keyword and {sel['per_account_cap']} per creator, so no keyword or creator fills the list.",
    ]
    if sel["selected"] < sel["requested"]:
        lines.append(f"> Fewer than {sel['requested']} Reels were available after the viral bar and the caps. Reaching {sel['requested']} at "
                     f"{sel['per_keyword_cap']} per keyword needs at least {sel['min_keywords_needed']} keywords that each produced enough viral Reels. "
                     "Scrape more keywords, or raise per_keyword_cap, or loosen the viral bar in config/settings.json.")
    if tr:
        lines.append(f"**Transcripts:** {tr.get('already_had', 0)} came with the scrape, {tr.get('transcribed', 0)} transcribed from the video, "
                     f"{tr.get('failed', 0) + tr.get('skipped', 0)} missing." + (f" ({tr['reason']})" if tr.get("reason") else ""))
    lines.append(f"**Earlier versions:** looked for each creator's weaker take on the same topic: {fu.get('fetched', 0)} other Reels checked, "
                 f"{fu.get('matched', 0)} on a matching topic, {len(res.twins)} winner/earlier-version pairs found." + (f" Problem: {fu['error']}" if fu.get("error") else ""))
    lines += ["", "**How to read this.** Every Reel was described *without the analyst seeing its view count*. Where the same creator also made a weaker "
              "version of the same topic, the two are compared directly; that is the strongest evidence here. Everywhere else it is description only. "
              "Views also depend on timing, sound, the algorithm and luck, which this cannot see.", ""]

    lines += ["## When a creator re-made a topic and the new version won", ""]
    if res.patterns:
        plural = lambda k: f"{k} pair" + ("" if k == 1 else "s")
        lines += [f"Changes that kept showing up in the same direction ({res.selection['pairs_in_statistics']} pairs, one per creator):", "",
                  "| What the winner did | Added in | Dropped in | Read |", "|---|---|---|---|"]
        for p in res.patterns[:12]:
            lines.append(f"| {describe_feature(p.feature)} | {plural(p.added)} | {plural(p.dropped)} | {p.read} |")
        lines += ["", "Rows overlap (for example “story loop: none” dropped and “myth-bust” added can be the same change counted twice), so read the top "
                  "one or two as a single story, not as many separate findings.", ""]
    else:
        n = res.selection.get("pairs_in_statistics", 0)
        lines += [f"{n} usable pair(s), one per creator, so far. No change repeated in the same direction often enough to report. "
                  "With a sign test, a pattern needs roughly 6 pairs all changing the same way before it can beat chance, so more weeks of data are needed. "
                  "Read the individual pairs below as examples, not as proof.", ""]

    if res.prevalence:
        lines += ["## What the viral Reels have in common (descriptive only)", "",
                  "How common each feature is among these winners. Common among winners does **not** mean it causes winning; "
                  "only the pair comparisons above and the topic comparisons in viral_analysis.md compare against non-viral Reels.", "",
                  "| Feature | Share of viral Reels | Reels judged |", "|---|---|---|"]
        for k, yes, n_ in res.prevalence:
            lines.append(f"| {describe_feature(k)} | {yes / n_:.0%} | {n_} |")
        lines.append("")

    twin_by_winner = {t["pair"].winner.id: t for t in res.twins}
    lines += ["## The Reels", ""]
    for rank, r in enumerate(res.reels, start=1):
        bd = res.breakdowns.get(r.id)
        lines.append(f"### {rank}. [@{r.account}]({r.url})" + (f": “{r.keyword}”" if r.keyword else "") + f" · topic: {r.topic}")
        lines.append(f"{_n(r.plays)} plays · {_n(r.likes)} likes · {_n(r.comments)} comments · {r.reach_ratio:.1f}× its follower count")
        twin = twin_by_winner.get(r.id)
        if twin:
            p = twin["pair"]
            when = {True: "posted earlier", False: "posted later", None: ""}[p.baseline_came_first]
            lines.append(f"**Same creator, same topic, earlier version:** [{_n(p.baseline.plays)} plays]({p.baseline.url}) {when}. "
                         f"This one got **{p.ratio:,.0f}×** as many.")
        lines.append("")
        if bd is None or bd.error:
            lines += [f"Breakdown unavailable: {bd.error if bd else 'not analysed'}", ""]
            continue
        lines.append(f"- **Hooks:** {_hook_line(bd)}")
        loop = bd.loop
        lines.append(f"- **Format / style:** {bd.format} · tone {bd.style.get('tone')} · pacing {bd.style.get('pacing')}")
        lines.append(f"- **Storytelling loop:** {loop['type']}" + (f". Opens: “{loop['open_loop']}”" if loop.get("open_loop") else "")
                     + (f". Pays off: “{loop['payoff']}”" if loop.get("payoff") else "") + (f". Re-hook: “{loop['re_hook']}”" if loop.get("re_hook") else ""))
        lines.append(f"- **Structure:** " + " → ".join(b["beat"] for b in bd.structure))
        lines.append(f"- **Spice:** {', '.join(bd.spice) or 'none'} · **CTA:** {bd.cta['type']}" + (f" (“{bd.cta['text']}”)" if bd.cta.get("text") else ""))
        if twin:
            if twin["added"] or twin["dropped"]:
                lines.append("- **What changed from the earlier version:** "
                             + ("added " + "; ".join(describe_feature(x) for x in twin["added"]) if twin["added"] else "")
                             + (" · " if twin["added"] and twin["dropped"] else "")
                             + ("dropped " + "; ".join(describe_feature(x) for x in twin["dropped"]) if twin["dropped"] else ""))
            ex = twin["explanation"]
            if ex.get("what_changed"):
                lines.append(f"- **Why it may have gone further:** {ex['what_changed']}")
            if ex.get("worth_testing"):
                lines.append("- **Worth testing:** " + "; ".join(describe_feature(x) for x in ex["worth_testing"]))
            for c in ex.get("caveats", []):
                lines.append(f"- Caveat: {c}")
            if twin["note"]:
                lines.append(f"- {twin['note']}")
            if ex.get("template"):
                lines += ["", f"> **Template to adapt (fill the [brackets] from your own experience):** {ex['template']}"]
        else:
            lines.append("- *No weaker version of this topic by the same creator was found, so nothing here shows what made it travel. Description only.*")
        lines.append("")
        if r.transcript:
            lines += ["<details><summary>Full transcript</summary>", "", r.transcript, "", "</details>", ""]
        else:
            lines += ["*Transcript not available: the scraper gave none and it could not be transcribed.*", ""]
    return "\n".join(lines)


def render_watchlist(rows, table: dict, date: str, sample: bool, k: float, history_runs: int) -> str:
    lines = [f"# Watchlist: week of {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic accounts and numbers. The format is real; the content is not.", ""]
    lines += [f"Each creator's **usual** is the median plays of their most recent Reels we have seen"
              f"{' (history from ' + str(history_runs) + ' earlier run(s) is included)' if history_runs else ' (this is the first run, so it uses only what was fetched today)'}. "
              f"A Reel is an outlier when it beats that usual by {k:g}× or more. A creator with fewer than 5 Reels seen has no usual yet, "
              "so nothing is flagged for them.", "", "## Creators", "",
              "| Creator | Reels seen | Usual plays | Outliers | Best outlier |", "|---|---|---|---|---|"]
    for h, t in sorted(table.items(), key=lambda kv: -(kv[1]["best_ratio"] or 0)):
        usual = f"{t['baseline']:,.0f}" if t["baseline"] else "not enough Reels yet"
        best = f"{t['best_ratio']:.0f}×" if t["best_ratio"] else "none"
        lines.append(f"| @{h} | {t['reels_seen']} | {usual} | {t['outliers']} | {best} |")
    lines += ["", "## Outlier feed", ""]
    if not rows:
        lines.append("No watched Reel beat its creator's usual by enough this week.")
    for w in rows:
        r = w.reel
        grow = f" · growing about {w.growth_per_day:,.0f} plays/day since last run" if w.growth_per_day else ""
        lines.append(f"- **{w.ratio:.0f}×** [@{r.account}]({r.url}): {r.plays:,} plays against a usual of {w.baseline:,.0f}{grow}")
    return "\n".join(lines)


FRAMEWORK_LEGEND = ("A framework is only as good as the evidence for it. **supported** = winners use it more than non-winners on the same topics "
                    "(or creators added it when a re-make won), after correcting for luck. **suggestive** = a pattern, but it could be chance. "
                    "**thin** = too little data. **mixed** = two kinds of evidence disagree. **common-to-both** = non-winners use it just as often, "
                    "so it is not what makes Reels win. **not-favoured** = creators tended to drop it when they won.")


def framework_table(board) -> list[str]:
    lines = ["| Framework | Evidence | Winners using it | Viral vs non-viral | Why |", "|---|---|---|---|---|"]
    for e in board:
        vs = f"{e.viral_yes}/{e.viral_n} vs {e.peer_yes}/{e.peer_n}" if e.peer_n else "no comparison"
        lines.append(f"| {e.fw['name']} | **{e.level}** | {e.n_library}/{e.library_total} | {vs} | {'; '.join(e.reasons)} |")
    return lines


def render_frameworks(board, date: str, sample: bool) -> str:
    lines = [f"# Storytelling frameworks, rated by this week's evidence: {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic data. The ratings show the format only.", ""]
    return "\n".join(lines + [FRAMEWORK_LEGEND, ""] + framework_table(board))


def render_script(res, date: str, sample: bool, cfg: dict) -> str:
    from .scriptwriter import CHECKS

    s, ev = res.script, res.evidence
    failing = {i.code for i in s.issues if i.severity == "error"}
    badge = {"ready": "✅ Ready to film", "needs_work": f"⚠️ Needs work: {len(failing)} unresolved check(s)", "failed": "❌ Could not be written"}[s.status]
    lines = [f"# {s.title or 'Script'}", "", f"**{badge}**" + (f" · {s.error}" if s.error else ""), ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Placeholder text from a rule-based stand-in. The structure is real; the words are not.", ""]
    lines += [f"- **Topic:** {s.topic} · **Angle:** {s.angle}",
              (f"- **Framework:** {ev.fw['name']} (evidence: {ev.level}). " + "; ".join(ev.reasons)) if ev else "- **Framework:** none",
              f"- **Length:** about {s.est_seconds(cfg['words_per_second']):.0f} seconds spoken (target {cfg['target_seconds']}) · written in {s.rounds} round(s)",
              f"- **Slot:** {'experiment' if res.slot == 'experiment' else 'data-backed'}", ""]
    if ev and ev.level not in ("supported", "suggestive"):
        lines += [f"> The evidence for this framework is **{ev.level}**, so treat this script as a test, not a proven format.", ""]
    if s.error:
        return "\n".join(lines)
    lines += ["## The first 3 seconds", "", "| | |", "|---|---|", f"| **Say** | {s.hooks.get('audio', '')} |",
              f"| **On-screen text** | {s.hooks.get('text', '')} |", f"| **Show** | {s.hooks.get('video', '')} |", ""]
    if s.hook_variants:
        lines += ["**Hooks to A/B test:**", ""]
        for i, v in enumerate(s.hook_variants, 1):
            lines.append(f"{i}. Say “{v['audio']}” · text “{v['text']}” · show {v['video']}" + (f" ({v['why']})" if v.get("why") else ""))
        lines.append("")
    lines += ["## Shot by shot", "", "| Time | Beat | Say | On-screen text | Show | Sound |", "|---|---|---|---|---|---|"]
    for b in s.beats:
        t = f"{b['start_s']:g}–{b['end_s']:g}s" if b["start_s"] is not None and b["end_s"] is not None else ""
        lines.append(f"| {t} | {b['beat']} | {b['spoken']} | {b['on_screen_text']} | {b['visual']} | {b['audio']} |")
    lines += ["", "## Caption and call to action", "", s.caption, "", " ".join(s.hashtags), "", f"**CTA ({s.cta.get('type', '')}):** {s.cta.get('text', '')}", ""]
    if s.needs_from_you:
        lines += ["## You need to supply", ""] + [f"- {x}" for x in s.needs_from_you] + [""]
    lines += ["## Checks", ""]
    for code, label in CHECKS:
        lines.append(f"- {'❌' if code in failing else '✅'} {label}")
    for i in s.issues:
        lines.append(f"  - {'**Fix:**' if i.severity == 'error' else 'Note:'} {i.message}")
    if res.references:
        lines += ["", "## Built from (structure only)", "",
                  "The writer was told how these winners were built, not what they said. Study them; do not copy them.", ""]
        lines += [f"- [@{r.account}]({r.url}), {r.plays:,} plays" for r in res.references]
    return "\n".join(lines)


def render_outliers(outliers, stats: dict, *, niche: str | None, days: int, k_usual: float, k_followers: float, date: str) -> str:
    lines = [f"# Viral outliers{' in ' + niche if niche else ''}: {date}", "",
             f"{stats['outliers']} outliers ({stats['strong']} strong) from {stats['considered']} Reels posted in the last {days} days, "
             f"out of {stats['reels_in_vault']} Reels in the vault. {stats['creators_with_a_usual']} creators have enough Reels stored to have a \"usual\".", "",
             f"**Strong** = beat that creator's own median by {k_usual:g}× or more. **Weak** = we only know the creator's size, so it is plays against "
             f"followers ({k_followers:g}× or more); a small account can spike for reasons that say nothing about the content, so treat these as leads, not proof. "
             "Watching more creators (`agent.py niche add-creators`) turns weak outliers into strong ones.", ""]
    if not outliers:
        return "\n".join(lines + ["No outliers yet. Harvest more (`agent.py harvest`), watch more creators, or lower the thresholds."])
    lines += ["| # | Reel | Niche | Keyword | Beat the usual by | Plays | Plays/day | Basis |", "|---|---|---|---|---|---|---|---|"]
    for i, o in enumerate(outliers, 1):
        r = o.reel
        lines.append(f"| {i} | [@{r.account}]({r.url}) | {r.niche or '-'} | {r.keyword or '-'} | **{o.ratio:.0f}×** | {r.plays:,} | {o.velocity:,.0f} | "
                     f"{'strong: own usual ' + format(o.usual, ',.0f') if o.strong else 'weak: vs followers'} |")
    return "\n".join(lines)


def render_formats(res, date: str, sample: bool, cards: int = 10) -> str:
    from .viral_analysis import describe_feature

    cov = res.coverage
    lines = [f"# Winning content formats: {date}", ""]
    if sample:
        lines += ["> **SAMPLE RUN.** Synthetic Reels and a rule-based stand-in analyst. Shows the format of the report, not anything real.", ""]
    lines += [f"Built from **{cov['outliers_analysed']} outliers** and **{cov['ordinary_reels_analysed']} ordinary Reels by the same creators**, "
              f"compared creator by creator ({cov['creators_compared']} creators, {cov['pooled'][0]} vs {cov['pooled'][1]} Reels). "
              "The analyst described each Reel *without seeing its view count*; the comparison is computed in code and corrected for testing many features at once.", ""]
    if cov["with_frames"] == 0:
        lines.append("> No video frames were available, so on-screen text hooks, visual hooks, format, tone and pacing were **not analysed**. "
                     "Only the spoken hook, story loop, spice, CTA and structure are covered.")
    if cov["weak_basis_outliers"]:
        lines.append(f"> {cov['weak_basis_outliers']} outlier(s) have no creator baseline (weak basis); they are described below but not used in the comparison.")
    for e in cov["errors"]:
        lines.append(f"> Error: {e}")
    lines += ["", "## What separates a creator's outliers from their ordinary Reels", ""]
    if res.contrasts:
        lines += ["| Feature | In outliers | In ordinary Reels | Gap | Read |", "|---|---|---|---|---|"]
        for c in res.contrasts[:12]:
            lines.append(f"| {describe_feature(c.feature)} | {c.viral_yes}/{c.viral_n} | {c.rest_yes}/{c.rest_n} | {c.gap:+.0%} | {c.read} |")
        lines += ["", "Rows overlap (one change can show up as several features), so read the top one or two as a single story.", ""]
    elif cov["creators_compared"] < 3:
        lines += [f"Only {cov['creators_compared']} creator(s) could be compared. Each needs at least 5 stored Reels (so we know their usual) plus an outlier, "
                  "and a pattern needs several creators. Watch more creators and harvest again.", ""]
    else:
        lines += ["No feature separated outliers from ordinary Reels by enough to report. That is a result, not a failure: with this sample, "
                  "presentation did not clearly differ.", ""]
    lines += ["## Storytelling frameworks, rated by this evidence", "", FRAMEWORK_LEGEND, ""] + framework_table(res.board) + [""]
    if res.prevalence:
        lines += ["## What the outliers have in common (descriptive only)", "",
                  "Common among outliers does **not** mean it causes winning. Only the comparison above checks that.", "",
                  "| Feature | Share of outliers | Reels judged |", "|---|---|---|"]
        lines += [f"| {describe_feature(k)} | {y / n:.0%} | {n} |" for k, y, n in res.prevalence]
        lines.append("")
    lines += ["## The outliers", ""]
    for rank, o in enumerate(res.outliers[:cards], 1):
        r, bd = o.reel, res.breakdowns.get(o.reel.id)
        lines.append(f"### {rank}. [@{r.account}]({r.url})" + (f" · {r.niche}" if r.niche else "") + (f" · “{r.keyword}”" if r.keyword else ""))
        lines.append(f"{r.plays:,} plays · **{o.ratio:.0f}×** " + (f"its usual of {o.usual:,.0f}" if o.strong else "its follower count (weak basis)"))
        lines.append("")
        if bd is None or bd.error:
            lines += [f"Breakdown unavailable: {bd.error if bd else 'not analysed'}", ""]
            continue
        loop = bd.loop
        lines += [f"- **Hooks:** {_hook_line(bd)}",
                  f"- **Format / style:** {bd.format} · tone {bd.style.get('tone')} · pacing {bd.style.get('pacing')}",
                  f"- **Story loop:** {loop['type']}" + (f". Opens: “{loop['open_loop']}”" if loop.get("open_loop") else "") + (f". Pays off: “{loop['payoff']}”" if loop.get("payoff") else ""),
                  f"- **Structure:** " + " → ".join(b["beat"] for b in bd.structure),
                  f"- **Spice:** {', '.join(bd.spice) or 'none'} · **CTA:** {bd.cta['type']}", ""]
        lines += (["<details><summary>Full transcript</summary>", "", r.transcript, "", "</details>", ""] if r.transcript
                  else ["*Transcript not available: the scraper gave none and it could not be transcribed.*", ""])
    return "\n".join(lines)
