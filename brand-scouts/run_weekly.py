#!/usr/bin/env python3
"""Weekly Instagram winners: harvest -> triage -> label -> group -> score -> angles -> shortlist.

    python3 run_weekly.py --sample     # offline demo on synthetic data
    python3 run_weekly.py --live       # Apify + Anthropic; needs keys and config/apify.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from scouts.angles import expand_angles, load_angles, shortlist
from scouts.library import run_library
from scouts.common import ROOT, Reel, load_env, load_json, read_lines, utcnow
from scouts.frameworks import load_frameworks, scoreboard
from scouts.playbook import EmptyPlaybook
from scouts.script_run import generate_scripts
from scouts.watchlist import append_snapshot, load_history, outlier_feed
from scouts.report import (render_frameworks, render_library, render_script, render_shortlist, render_viral_analysis,
                           render_watchlist, write_outputs)
from scouts.scoring import cap_topics, compute_factors, score_brand_match, score_topics
from scouts.topics import group_topics, label_reels
from scouts.viral_analysis import analyse_topics, load_vocab, spread
from scouts.triage import TriageConfig, triage_split

STATE = ROOT / "data" / "state" / "last_week.json"
WATCH_STATE = ROOT / "data" / "state" / "watchlist.jsonl"


def load_sample(now) -> list[Reel]:
    reels = []
    for d in load_json(ROOT / "data" / "sample_reels.json"):
        d = dict(d)
        d["posted_at"] = now - timedelta(days=d.pop("posted_days_ago"))
        d["keyword"] = d.get("source", "").lstrip("#")
        reels.append(Reel.from_dict(d))
    return reels


def sample_followups_loader(now):
    data = load_json(ROOT / "data" / "sample_followups.json")

    def load(accounts):
        wanted = {a.lower() for a in accounts}
        out = []
        for d in data:
            if d["account"].lower() in wanted:
                d = dict(d)
                d["posted_at"] = now - timedelta(days=d.pop("posted_days_ago"))
                out.append(Reel.from_dict(d))
        return out
    return load


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true", help="synthetic data, rule-based labelling, no keys needed")
    mode.add_argument("--live", action="store_true", help="real Apify harvest and Anthropic labelling")
    ap.add_argument("--out", help="output folder (default out/week_<date>)")
    ap.add_argument("--max-reels", type=int, help="cap Reels fetched in a live run")
    ap.add_argument("--save-state", action="store_true", help="remember this week's topics for next week's momentum")
    args = ap.parse_args(argv)

    load_env()
    settings = load_json(ROOT / "config" / "settings.json")
    now = utcnow()
    date = now.strftime("%Y-%m-%d")
    out_dir = Path(args.out) if args.out else ROOT / "out" / f"week_{date}"
    brief = (ROOT / "config" / "brand_brief.md").read_text(encoding="utf-8")
    known_topics = read_lines(ROOT / "config" / "topics.txt")
    angles = load_angles(ROOT / "config" / "angles.txt")
    followups_loader, transcriber = None, None
    stats: dict = {"mode": "sample" if args.sample else "live", "date": date}

    if args.sample:
        from scouts.fake_llm import FakeLLM

        llm, reels = FakeLLM(), load_sample(now)
        followups_loader = sample_followups_loader(now)
    else:
        missing = [k for k in ("APIFY_TOKEN", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
        if missing:
            print(f"Missing in .env: {', '.join(missing)}", file=sys.stderr)
            return 2
        from scouts.instagram_harvest import harvest
        from scouts.llm import AnthropicLLM

        llm = AnthropicLLM()
        cap = args.max_reels or settings["harvest"].get("max_reels")
        creators_file = ROOT / "config" / "creators.txt"
        creators = read_lines(creators_file) if creators_file.exists() else []
        apify_cfg, token = load_json(ROOT / "config" / "apify.json"), os.environ["APIFY_TOKEN"]
        reels, hstats = harvest(read_lines(ROOT / "config" / "keywords.txt"), apify_cfg, token, cap, creators)
        from scouts.instagram_harvest import harvest_profiles
        per = settings.get("viral_library", {}).get("followup_per_account")
        followups_loader = lambda accounts: harvest_profiles(accounts, apify_cfg, token, per)[0]
        from scouts.transcribe import FasterWhisperTranscriber, LazyTranscriber
        transcriber = LazyTranscriber(FasterWhisperTranscriber)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "raw_sample.json").write_text(json.dumps(hstats.pop("raw_sample"), indent=2, default=str), encoding="utf-8")
        stats["harvest"] = hstats
        if not reels:
            print("Harvest returned no usable Reels. Check raw_sample.json and the field mapping.", file=sys.stderr)
            return 3

    tcfg = TriageConfig.from_dict(settings["triage"])
    if args.sample:  # the sample pool is tiny, so a strict viral bar would leave almost nothing
        tcfg.min_heat, tcfg.min_outperformance = 30.0, 0.0   # loose, so some Reels land below the bar and act as same-topic peers
        stats["note"] = "viral bar loosened in sample mode"
    kept, below_bar, stats["triage"] = triage_split(reels, tcfg, now)
    if stats["triage"].get("warning"):
        print("WARNING:", stats["triage"]["warning"], file=sys.stderr)
    labelled, stats["labelling"] = label_reels(kept, llm, known_topics, angles=list(angles))
    if not labelled:
        print(f"No Reels were labelled. Errors: {stats['labelling']['errors'] or 'none'}", file=sys.stderr)
        return 3

    topics = group_topics(labelled)
    prev = load_json(STATE) if STATE.exists() else {}
    compute_factors(topics, prev, EmptyPlaybook())
    stats["topics_found"] = len(topics)
    topics = cap_topics(topics, settings["scoring"].get("max_topics"))
    score_brand_match(topics, llm, brief)
    ranked = score_topics(topics, settings["scoring"]["weights"])
    stats["topics"] = len(ranked)

    sl = settings["shortlist"]
    top = ranked[: sl["expand_top"]]
    ideas = expand_angles(top, llm, angles, brief, EmptyPlaybook())
    picks, notes = shortlist(top, ideas, sl["topics"], sl["angles_per_topic"], sl["experiment_slots"])
    stats["angle_ideas"] = len(ideas)
    stats["shortlist"] = {"topics": len(picks), "experiments": sum(p.slot == "experiment" for p in picks), "notes": notes}

    va, peers_all, frames = None, [], None
    vcfg = settings.get("viral_analysis", {})
    if vcfg.get("enabled", True) and top:
        # Same-topic Reels that did NOT go viral: the comparison group. Label them against the top topics' names.
        pool = spread(sorted(below_bar, key=lambda r: -r.heat), vcfg["peer_pool_max"])
        peers, stats["peer_labelling"] = label_reels(pool, llm, [t.name for t in top], angles=list(angles))
        by_topic = {t.name.lower(): t for t in top}
        for r in peers:
            if r.topic.lower() in by_topic:
                by_topic[r.topic.lower()].peers.append(r)
                peers_all.append(r)
        stats["peers_matched_to_top_topics"] = len(peers_all)
        frames = None
        if not args.sample and vcfg.get("frames", True):
            from scouts.frames import FfmpegFrames, ffmpeg_available
            frames = FfmpegFrames() if ffmpeg_available() else None
            if frames is None:
                print("WARNING: ffmpeg not found, so video and on-screen-text hooks will not be analysed.", file=sys.stderr)
        va = analyse_topics(top, llm, load_vocab(), brief, frames, viral_per_topic=vcfg["viral_per_topic"],
                            peers_per_topic=vcfg["peers_per_topic"], max_reels=vcfg["max_reels"],
                            min_group=vcfg["min_group"], min_gap=vcfg["min_gap"])
        stats["viral_analysis"] = va.coverage

    lib, lcfg = None, settings.get("viral_library", {})
    if lcfg.get("enabled", True) and labelled:
        if not args.sample and frames is None and vcfg.get("frames", True):
            from scouts.frames import FfmpegFrames, ffmpeg_available
            frames = FfmpegFrames() if ffmpeg_available() else None
        lib = run_library(labelled, peers_all, llm, load_vocab(), brief, list(angles), lcfg, followups_loader=followups_loader,
                          transcriber=transcriber, frames=frames, breakdowns=(va.breakdowns if va else None))
        stats["viral_library"] = {"reels": len(lib.reels), **lib.selection, "twin_pairs": len(lib.twins), "followups": lib.followups, "transcripts": lib.transcripts}

    # --- competitor watchlist: usual level per creator, and an outlier feed across runs
    wl_rows = wl_table = None
    wcfg = settings.get("watchlist", {})
    creators_file = ROOT / "config" / "creators.txt"
    handles = [h.lstrip("@") for h in read_lines(creators_file)] if creators_file.exists() else []
    watch_pool = [r for r in reels if r.source == "creator"]
    if args.sample and lib:
        handles = sorted({r.account for r in lib.reels})[:6]
        watch_pool = [r for r in reels if r.account in handles] + (followups_loader(handles) if followups_loader else [])
    if handles and watch_pool:
        history = load_history(WATCH_STATE)
        wl_rows, wl_table, _ = outlier_feed(watch_pool, history, handles, k=wcfg["outlier_k"], max_age_days=wcfg["max_age_days"],
                                            min_reels=wcfg["min_reels"], now=now)
        stats["watchlist"] = {"creators": len(handles), "outliers": len(wl_rows), "earlier_snapshots": len(history)}
        if args.save_state:
            append_snapshot(WATCH_STATE, watch_pool, now)

    # --- storytelling frameworks rated by evidence, then scripts
    board, scripts = [], []
    scfg = settings.get("scripts", {})
    if scfg.get("enabled", True) and lib and picks:
        all_feats = {**(va.features if va else {}), **lib.features}
        pooled_ok = va and va.pooled_basis.startswith("viral vs")
        v_ids, p_ids = (va.pooled_ids if pooled_ok else ((), ()))
        seen_accounts, pair_feats = set(), []
        for t in sorted(lib.twins, key=lambda t: -t["pair"].ratio):
            p = t["pair"]
            if p.account.lower() not in seen_accounts and p.winner.id in all_feats and p.baseline.id in all_feats:
                seen_accounts.add(p.account.lower())
                pair_feats.append((all_feats[p.winner.id], all_feats[p.baseline.id]))
        board = scoreboard(load_frameworks(), [all_feats[r.id] for r in lib.reels if r.id in all_feats],
                           [all_feats[i] for i in v_ids if i in all_feats], [all_feats[i] for i in p_ids if i in all_feats], pair_feats)
        material_file = ROOT / "config" / "my_material.md"
        material = material_file.read_text(encoding="utf-8") if material_file.exists() else ""
        scripts = generate_scripts(picks, board, lib.reels, lib.breakdowns, all_feats, angles, llm, load_vocab(), brief, material, scfg)
        stats["scripts"] = {"written": len(scripts), "ready": sum(r.script.status == "ready" for r in scripts),
                            "needs_work": sum(r.script.status == "needs_work" for r in scripts), "failed": sum(r.script.status == "failed" for r in scripts)}

    write_outputs(out_dir, date, labelled, ranked, stats, settings["scoring"]["weights"], settings["scoring"]["top_n"], args.sample)
    (out_dir / "angles.json").write_text(json.dumps([i.to_dict() for i in ideas], indent=2), encoding="utf-8")
    (out_dir / "shortlist.json").write_text(json.dumps([p.to_dict() for p in picks], indent=2), encoding="utf-8")
    if va:
        by_id = {r.id: r for t in top for r in t.reels + t.peers}
        (out_dir / "viral_analysis.md").write_text(render_viral_analysis(va, top, by_id, date, args.sample), encoding="utf-8")
        (out_dir / "viral_analysis.json").write_text(json.dumps({
            "pooled": {"basis": va.pooled_basis, "n": va.pooled_n, "contrasts": [c.to_dict() for c in va.pooled]},
            "topics": [t.to_dict() for t in va.topics],
            "breakdowns": {k: v.to_dict() for k, v in va.breakdowns.items()}}, indent=2, default=str), encoding="utf-8")
    if lib:
        (out_dir / "viral_reels.md").write_text(render_library(lib, date, args.sample), encoding="utf-8")
        (out_dir / "viral_reels.json").write_text(json.dumps({
            "selection": lib.selection, "followups": lib.followups, "transcripts": lib.transcripts,
            "patterns": [p.to_dict() for p in lib.patterns],
            "reels": [{**r.to_dict(), "breakdown": lib.breakdowns[r.id].to_dict() if r.id in lib.breakdowns else None} for r in lib.reels],
            "twins": [{"winner": t["pair"].winner.id, "earlier_version": t["pair"].baseline.id, "ratio": round(t["pair"].ratio, 1),
                       "added": t["added"], "dropped": t["dropped"], "explanation": t["explanation"], "note": t["note"]} for t in lib.twins]},
            indent=2, default=str), encoding="utf-8")
    if wl_table is not None:
        (out_dir / "watchlist.md").write_text(render_watchlist(wl_rows, wl_table, date, args.sample, wcfg["outlier_k"],
                                                               len({r[0]["seen"] for r in load_history(WATCH_STATE).values()})), encoding="utf-8")
    if board:
        (out_dir / "frameworks.md").write_text(render_frameworks(board, date, args.sample), encoding="utf-8")
        (out_dir / "frameworks.json").write_text(json.dumps([e.to_dict() for e in board], indent=2), encoding="utf-8")
    if scripts:
        (out_dir / "scripts").mkdir(exist_ok=True)
        for n, res in enumerate(scripts, 1):
            slug = "".join(c if c.isalnum() else "-" for c in res.script.topic.lower()).strip("-")[:40]
            (out_dir / "scripts" / f"{n:02d}-{slug}.md").write_text(render_script(res, date, args.sample, scfg), encoding="utf-8")
        (out_dir / "scripts.json").write_text(json.dumps([{**r.script.to_dict(), "framework_evidence": r.evidence.to_dict() if r.evidence else None,
                                                          "references": [x.url for x in r.references]} for r in scripts], indent=2, default=str), encoding="utf-8")
    (out_dir / "shortlist.md").write_text(render_shortlist(picks, notes, date, args.sample, sl["experiment_slots"]), encoding="utf-8")
    if args.save_state:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({t.name: t.total_plays for t in ranked}, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2, default=str))
    print(f"\nWrote {out_dir}/shortlist.md, scripts/, viral_analysis.md, viral_reels.md, watchlist.md, frameworks.md and top10.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
