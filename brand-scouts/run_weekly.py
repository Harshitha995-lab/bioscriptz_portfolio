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
from scouts.common import ROOT, Reel, load_env, load_json, read_lines, utcnow
from scouts.playbook import EmptyPlaybook
from scouts.report import render_shortlist, write_outputs
from scouts.scoring import cap_topics, compute_factors, score_brand_match, score_topics
from scouts.topics import group_topics, label_reels
from scouts.triage import TriageConfig, triage

STATE = ROOT / "data" / "state" / "last_week.json"


def load_sample(now) -> list[Reel]:
    reels = []
    for d in load_json(ROOT / "data" / "sample_reels.json"):
        d = dict(d)
        d["posted_at"] = now - timedelta(days=d.pop("posted_days_ago"))
        reels.append(Reel.from_dict(d))
    return reels


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
    stats: dict = {"mode": "sample" if args.sample else "live", "date": date}

    if args.sample:
        from scouts.fake_llm import FakeLLM

        llm, reels = FakeLLM(), load_sample(now)
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
        reels, hstats = harvest(read_lines(ROOT / "config" / "keywords.txt"), load_json(ROOT / "config" / "apify.json"),
                                os.environ["APIFY_TOKEN"], cap, creators)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "raw_sample.json").write_text(json.dumps(hstats.pop("raw_sample"), indent=2, default=str), encoding="utf-8")
        stats["harvest"] = hstats
        if not reels:
            print("Harvest returned no usable Reels. Check raw_sample.json and the field mapping.", file=sys.stderr)
            return 3

    tcfg = TriageConfig.from_dict(settings["triage"])
    if args.sample:  # the sample pool is tiny, so a strict viral bar would leave almost nothing
        tcfg.min_heat, tcfg.min_outperformance = 0.0, 0.0
        stats["note"] = "viral bar switched off in sample mode"
    kept, stats["triage"] = triage(reels, tcfg, now)
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

    write_outputs(out_dir, date, labelled, ranked, stats, settings["scoring"]["weights"], settings["scoring"]["top_n"], args.sample)
    (out_dir / "angles.json").write_text(json.dumps([i.to_dict() for i in ideas], indent=2), encoding="utf-8")
    (out_dir / "shortlist.json").write_text(json.dumps([p.to_dict() for p in picks], indent=2), encoding="utf-8")
    (out_dir / "shortlist.md").write_text(render_shortlist(picks, notes, date, args.sample, sl["experiment_slots"]), encoding="utf-8")
    if args.save_state:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({t.name: t.total_plays for t in ranked}, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2, default=str))
    print(f"\nWrote {out_dir}/shortlist.md and top10.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
