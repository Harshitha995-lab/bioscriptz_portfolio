#!/usr/bin/env python3
"""Weekly Instagram winners: harvest -> triage -> label -> group -> score -> report.

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

from scouts.common import ROOT, Reel, load_env, load_json, read_lines, utcnow
from scouts.playbook import EmptyPlaybook
from scouts.report import write_outputs
from scouts.scoring import compute_factors, score_brand_match, score_topics
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
        reels, hstats = harvest(read_lines(ROOT / "config" / "keywords.txt"), load_json(ROOT / "config" / "apify.json"), os.environ["APIFY_TOKEN"], cap)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "raw_sample.json").write_text(json.dumps(hstats.pop("raw_sample"), indent=2, default=str), encoding="utf-8")
        stats["harvest"] = hstats
        if not reels:
            print("Harvest returned no usable Reels. Check raw_sample.json and the field mapping.", file=sys.stderr)
            return 3

    kept, stats["triage"] = triage(reels, TriageConfig.from_dict(settings["triage"]), now)
    labelled, stats["labelling"] = label_reels(kept, llm, known_topics)
    if not labelled:
        print(f"No Reels were labelled. Errors: {stats['labelling']['errors'] or 'none'}", file=sys.stderr)
        return 3

    topics = group_topics(labelled)
    prev = load_json(STATE) if STATE.exists() else {}
    compute_factors(topics, prev, EmptyPlaybook())
    score_brand_match(topics, llm, brief)
    ranked = score_topics(topics, settings["scoring"]["weights"])
    stats["topics"] = len(ranked)

    write_outputs(out_dir, date, labelled, ranked, stats, settings["scoring"]["weights"], settings["scoring"]["top_n"], args.sample)
    if args.save_state:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({t.name: t.total_plays for t in ranked}, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2, default=str))
    print(f"\nWrote {out_dir}/top10.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
