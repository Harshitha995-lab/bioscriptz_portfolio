#!/usr/bin/env python3
"""Instagram outlier agent, five steps, built for Apify's free plan.

    1  niche      choose niches, keywords and creators to watch
    2  harvest / outliers   pull Reels (budget-guarded), then find the viral outliers
    3  analyse    transcripts + hook breakdowns; which content formats win
    4  script     write or remix a production-ready script
    5  vault      organise, tag, search and export scripts

Add --sample to any command to try it offline on synthetic data (separate vault, no keys).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from scouts import budget
from scouts.common import ROOT, Reel, load_env, load_json, utcnow
from scouts.niches import Niches
from scouts.outliers import find_outliers
from scouts.vault import STATUSES, Vault

SAMPLE_VAULT = ROOT / "data" / "sample_vault.db"
OUT = ROOT / "out" / "agent"


class UsageError(Exception):
    """A problem the user can fix (exit code 2)."""


class BudgetError(Exception):
    """The run would not fit in the free plan (exit code 3)."""


def load_sample_reels(niches: Niches, now) -> list[Reel]:
    """Synthetic Reels. Keyword Reels get their niche from the watchlist keywords; profile Reels carry their own."""
    kmap, reels = niches.keyword_map(), []
    for name in ("sample_reels.json", "sample_profiles.json"):
        for d in load_json(ROOT / "data" / name):
            d = dict(d)
            d["posted_at"] = now - timedelta(days=d.pop("posted_days_ago"))
            if not d.get("keyword") and d.get("source") not in ("profile", "creator", None):
                d["keyword"] = d["source"].lstrip("#")
            r = Reel.from_dict(d)
            r.niche = r.niche or kmap.get(r.keyword.lower(), "")
            reels.append(r)
    return reels


def tag_niches(reels: list[Reel], niches: Niches) -> None:
    kmap = niches.keyword_map()
    cmap = {k.lower(): v for k, v in niches.creator_map().items()}
    for r in reels:
        if r.niche:
            continue
        r.niche = kmap.get(r.keyword.lower().lstrip("#"), "") or cmap.get(r.account.lower(), "")


def get_price(args, cfg: dict) -> tuple[float | None, str]:
    price = args.price if getattr(args, "price", None) is not None else cfg.get("price_per_1000_results_usd")
    if price is not None and price <= 0:
        raise UsageError("The price per 1,000 results must be above zero.")
    return price, ("from --price" if getattr(args, "price", None) is not None else "from config/apify.json")


# ---------------------------------------------------------------------------- commands
def cmd_niche(args, ctx) -> int:
    ns: Niches = ctx["niches"]
    a = args.niche_cmd
    try:
        if a == "list":
            for n in ns.items:
                print(f"{n.name}: {len(n.keywords)} keywords, {len(n.creators)} creators")
                for k in n.keywords:
                    print(f"    keyword  {k}")
                for c in n.creators:
                    print(f"    creator  @{c}")
            if not ns.items:
                print("No niches yet. Add one: agent.py niche add \"Personal branding\"")
            return 0
        if a == "add":
            ns.add_niche(args.name)
        elif a == "remove":
            ns.remove_niche(args.name)
        elif a == "add-keywords":
            added, skipped = ns.add_keywords(args.name, args.items)
            print(f"Added {added}." + (f" Problems: {', '.join(skipped)}" if skipped else ""))
        elif a == "add-creators":
            added, skipped = ns.add_creators(args.name, args.items)
            print(f"Added {added}." + (f" Problems: {', '.join(skipped)}" if skipped else ""))
        elif a == "remove-keyword":
            print("Removed." if ns.remove_keyword(args.name, args.item) else "Not found.")
        elif a == "remove-creator":
            print("Removed." if ns.remove_creator(args.name, args.item) else "Not found.")
        ns.save()
    except (KeyError, ValueError) as exc:
        raise UsageError(str(exc.args[0] if exc.args else exc)) from exc
    return 0


def cmd_harvest(args, ctx) -> int:
    ns, vault, settings = ctx["niches"], ctx["vault"], ctx["settings"]
    now = utcnow()
    try:
        keywords, creators = ns.keyword_lines(args.niche), ns.creators(args.niche)
    except KeyError as exc:
        raise UsageError(str(exc.args[0])) from exc
    if not keywords and not creators:
        raise UsageError("Nothing to harvest. Add keywords or creators: agent.py niche add-keywords \"Personal branding\" '#personalbranding'")

    if ctx["sample"]:
        reels = load_sample_reels(ns, now)
        if args.niche:
            reels = [r for r in reels if r.niche.lower() == args.niche.lower()]
        new, upd = vault.upsert_reels(reels, now)
        vault.record_run("harvest-sample", 0.0, len(reels), "synthetic data, no Apify call")
        print(f"[sample] Stored {len(reels)} synthetic Reels ({new} new, {upd} updated). Nothing was spent.")
        return 0

    apify_cfg = load_json(ROOT / "config" / "apify.json")
    price, price_src = get_price(args, apify_cfg)
    if price is None and not args.dry_run:
        raise UsageError("Set price_per_1000_results_usd in config/apify.json (or pass --price). Copy it from the actor's Pricing tab; "
                         "without it the free-plan budget cannot be protected.")
    spent = vault.month_spend(now)
    remaining = max(budget.FREE_CREDIT_USD - spent, 0.0)
    ref_price = budget.ASSUMED_PRICE_PER_1000 if price is None else price
    rec_kw, rec_cr = budget.recommend(remaining, ref_price, len(keywords), len(creators))
    per_kw = args.per_keyword if args.per_keyword is not None else rec_kw
    per_cr = args.per_creator if args.per_creator is not None else rec_cr
    if per_kw < 0 or per_cr < 0:
        raise UsageError("--per-keyword and --per-creator cannot be negative.")
    plan = budget.make_plan(len(keywords), len(creators), per_kw, per_cr, price)
    ok, _, msg = budget.check(plan, spent)

    print(f"Month so far: ${spent:.2f} of ${budget.FREE_CREDIT_USD:.2f}.")
    print(f"Plan: {len(keywords)} keywords × {per_kw} + {len(creators)} creators × {per_cr} = {plan.results:,} results")
    print(f"Price: ${plan.price_per_1000:.2f} per 1,000 ({'ASSUMED, not your actor\'s real price' if plan.price_assumed else price_src}).")
    print(msg)
    if len(creators) == 0:
        print("Note: no creators are watched, so every outlier will be 'weak' (judged against follower count). "
              "Add creators: agent.py niche add-creators <niche> handle1 handle2 …")
    elif per_cr and per_cr < 5:
        print("Note: fewer than 5 Reels per creator gives no 'usual' to compare against.")
    if args.dry_run:
        print("Dry run: nothing was fetched.")
        return 0
    if not ok and not args.force:
        raise BudgetError("Refusing to run. (--force overrides this check, but Apify may then bill beyond the free credit.)")
    if plan.results == 0:
        raise UsageError("The plan fetches zero results. Raise --per-keyword or --per-creator.")
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise UsageError("APIFY_TOKEN is missing. Put it in .env (see .env.example); never paste it into chat.")

    harvester = ctx.get("harvester")
    if harvester is None:
        from scouts.instagram_harvest import harvest as harvester
    n_runs = budget.runs_needed(len(keywords), len(creators), per_kw, per_cr)
    cap = budget.per_run_cap(remaining, n_runs)
    reels, info = harvester(keywords if per_kw else [], apify_cfg, token, None, creators if per_cr else [],
                            per_keyword=per_kw, per_creator=per_cr, run_cap_usd=cap)
    tag_niches(reels, ns)
    new, upd = vault.upsert_reels(reels, now)
    usage = info.get("usage_usd")
    cost, how = (usage, "reported by Apify") if usage is not None else (plan.est_cost, "ESTIMATED: Apify reported no usage")
    vault.record_run("harvest", cost, len(reels), f"{how}; {len(keywords)} keywords, {len(creators)} creators")
    print(f"Fetched {len(reels):,} Reels ({new} new, {upd} refreshed). Cost ${cost:.2f} ({how}).")
    print(f"Skipped as unusable: {info.get('skipped', 0)}. Check your Apify console for the true bill.")
    if not reels:
        print("No usable Reels came back. Check the actor's input template and field_map in config/apify.json.", file=sys.stderr)
        return 3
    return 0


def cmd_usage(args, ctx) -> int:
    vault = ctx["vault"]
    spent = vault.month_spend()
    print(f"This month: ${spent:.2f} of ${budget.FREE_CREDIT_USD:.2f} (as recorded here; Apify's console is the source of truth).")
    for r in vault.runs()[:10]:
        print(f"  {r['ts'][:16]}  {r['kind']:<15} ${r['cost_usd']:.2f}  {r['results']:>5} results  {r['note']}")
    return 0


def _outliers(args, ctx):
    t = ctx["settings"]["agent"]["outliers"]
    reels = ctx["vault"].reels()
    if not reels:
        raise UsageError("The vault is empty. Run `agent.py harvest` first.")
    if args.niche:
        ctx["niches"].require(args.niche)
    days = args.days if args.days is not None else t["days"]
    k_usual = args.k if args.k is not None else t["k_usual"]
    k_fol = args.k_followers if args.k_followers is not None else t["k_followers"]
    outs, stats = find_outliers(reels, niche=args.niche, days=days, min_plays=args.min_plays if args.min_plays is not None else t["min_plays"],
                                k_usual=k_usual, k_followers=k_fol, min_reels=t["min_reels_for_usual"], now=ctx["now"])
    return outs, stats, days, k_usual, k_fol


def cmd_outliers(args, ctx) -> int:
    from scouts.report import render_outliers
    try:
        outs, stats, days, k_usual, k_fol = _outliers(args, ctx)
    except KeyError as exc:
        raise UsageError(str(exc.args[0])) from exc
    text = render_outliers(outs, stats, niche=args.niche, days=days, k_usual=k_usual, k_followers=k_fol, date=ctx["now"].strftime("%Y-%m-%d"))
    path = Path(args.out) if args.out else OUT / "outliers.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"{stats['outliers']} outliers ({stats['strong']} strong). Written to {path}")
    for o in outs[:5]:
        print(f"  {o.ratio:>5.0f}×  {'strong' if o.strong else 'weak  '}  @{o.reel.account}  {o.reel.id}  {o.reel.url}")
    return 0


def cmd_analyse(args, ctx) -> int:
    from scouts.formats import analyse_outliers
    from scouts.report import render_formats
    from scouts.viral_analysis import load_vocab
    try:
        outs, stats, *_ = _outliers(args, ctx)
    except KeyError as exc:
        raise UsageError(str(exc.args[0])) from exc
    if not outs:
        raise UsageError("No outliers to analyse yet. Run `agent.py outliers` to see why.")
    a = ctx["settings"]["agent"]["analyse"]
    frames, transcriber = None, None
    if not ctx["sample"]:
        from scouts.frames import FfmpegFrames, ffmpeg_available
        from scouts.transcribe import FasterWhisperTranscriber, LazyTranscriber
        frames = FfmpegFrames() if ffmpeg_available() else None
        if frames is None:
            print("ffmpeg not found: text and video hooks, format and pacing will be reported as 'not analysed'.")
        transcriber = LazyTranscriber(FasterWhisperTranscriber)
    res = analyse_outliers(ctx["vault"], outs, ctx["llm"], load_vocab(), frames=frames, transcriber=transcriber,
                           top=args.top or a["top"], normals_per_creator=a["normals_per_creator"], min_group=a["min_group"], min_gap=a["min_gap"])
    text = render_formats(res, ctx["now"].strftime("%Y-%m-%d"), ctx["sample"])
    path = Path(args.out) if args.out else OUT / "formats.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Analysed {res.coverage['outliers_analysed']} outliers against {res.coverage['ordinary_reels_analysed']} ordinary Reels "
          f"({res.coverage['creators_compared']} creators compared). Written to {path}")
    return 0


def cmd_compare(args, ctx) -> int:
    from scouts import research
    from scouts.viral_analysis import load_vocab
    reels = [r for r in ctx["vault"].reels(args.niche) if r.transcript][: args.n]
    if len(reels) < 3:
        raise UsageError("Need at least 3 stored Reels with transcripts to compare models. Run harvest/analyse first.")
    if ctx["sample"]:
        from scouts.fake_llm import FakeLLM
        a = b = FakeLLM()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise UsageError("ANTHROPIC_API_KEY is missing. Put it in .env (see .env.example).")
        from scouts.llm import AnthropicLLM
        a, b = AnthropicLLM(args.a), AnthropicLLM(args.b)
    res = research.compare_models(reels, a, b, load_vocab())
    print(("[sample: the same stand-in analyst is used for both, so this always agrees] " if ctx["sample"] else "") + f"{res['both_ok']} of {res['reels']} Reels analysed by both ({args.a} vs {args.b}); failures {res['failed_a']} / {res['failed_b']}.")
    for k, v in res["fields"].items():
        print(f"  {k:<22} agree on {v['agree']}/{v['of']}")
    for d in res["differences"][:15]:
        print(f"  DIFF {d['field']}: {d['a']!r} vs {d['b']!r}  {d['reel']}")
    print("Agreement is not accuracy. Read the DIFF Reels yourself: whichever model is right on those decides which to use.")
    return 0


def cmd_script(args, ctx) -> int:
    from scouts.agent_script import write_one
    from scouts.angles import load_angles
    from scouts.report import render_script
    from scouts.viral_analysis import load_vocab
    brief = (ROOT / "config" / "brand_brief.md").read_text(encoding="utf-8")
    mat_path = ROOT / "config" / "my_material.md"
    material = mat_path.read_text(encoding="utf-8") if mat_path.exists() else ""
    cfg = ctx["settings"]["scripts"]
    meanings = load_angles(ROOT / "config" / "angles.txt")
    if args.angle and args.angle not in meanings:
        raise UsageError(f"Unknown angle '{args.angle}'. Choose from: {', '.join(meanings)}")
    try:
        sid, res = write_one(ctx["vault"], ctx["llm"], load_vocab(), brief, material, cfg, topic=args.topic, niche=args.niche or "",
                             from_reel_id=args.from_reel, angle=args.angle, angle_meanings=meanings)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    text = render_script(res, ctx["now"].strftime("%Y-%m-%d"), ctx["sample"], cfg)
    print(text)
    print(f"\nSaved to the vault as script #{sid} (status: drafted).")
    return 0


def cmd_vault(args, ctx) -> int:
    from scouts.export import export_scripts
    vault, a = ctx["vault"], args.vault_cmd
    if a == "stats":
        print(f"Reels {vault.count('reels')} · breakdowns {vault.count('breakdowns')} · scripts {vault.count('scripts')} · "
              f"spent this month ${vault.month_spend():.2f}")
        return 0
    if a in ("list", "search", "export"):
        rows = vault.scripts(status=args.status, niche=args.niche, tag=args.tag, search=getattr(args, "text", None))
        if a == "export":
            if not rows:
                raise UsageError("No scripts match those filters.")
            path = Path(args.out) if args.out else OUT / f"scripts.{args.format}"
            try:
                export_scripts(rows, args.format, path, ctx["settings"]["scripts"], ctx["now"].strftime("%Y-%m-%d"))
            except RuntimeError as exc:
                raise UsageError(str(exc)) from exc
            print(f"Exported {len(rows)} scripts to {path}")
            return 0
        for r in rows:
            print(f"#{r['id']:<4} {r['status']:<9} {r['quality']:<10} {r['niche'] or '-':<18} {r['title'][:50]}  [{', '.join(r['tags'])}]")
        if not rows:
            print("No scripts.")
        return 0
    row = vault.get_script(args.id)
    if row is None:
        raise UsageError(f"No script #{args.id}.")
    if a == "show":
        from scouts.agent_script import rebuild_result
        from scouts.report import render_script
        print(render_script(rebuild_result(row), ctx["now"].strftime("%Y-%m-%d"), ctx["sample"], ctx["settings"]["scripts"]))
        if row["notes"]:
            print(f"\nNotes: {row['notes']}")
        return 0
    try:
        if a == "status":
            vault.update_script(args.id, status=args.value)
        elif a == "tag":
            vault.update_script(args.id, add_tags=args.tags)
        elif a == "untag":
            vault.update_script(args.id, remove_tags=args.tags)
        elif a == "note":
            vault.update_script(args.id, notes=args.text)
        elif a == "delete":
            if not args.yes:
                raise UsageError("Deleting is permanent. Add --yes to confirm.")
            vault.delete_script(args.id)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print("Done.")
    return 0


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="synthetic data and rule-based analysis: no keys, no spend, separate vault")
    ap.add_argument("--vault", help="path of the vault database (default data/vault.db, or data/sample_vault.db with --sample)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("niche", help="step 1: your niches, keywords and creators").add_subparsers(dest="niche_cmd", required=True)
    n.add_parser("list")
    for c in ("add", "remove"):
        n.add_parser(c).add_argument("name")
    for c in ("add-keywords", "add-creators"):
        p = n.add_parser(c)
        p.add_argument("name")
        p.add_argument("items", nargs="+")
    for c in ("remove-keyword", "remove-creator"):
        p = n.add_parser(c)
        p.add_argument("name")
        p.add_argument("item")

    h = sub.add_parser("harvest", help="fetch Reels from Apify inside the free budget")
    h.add_argument("--niche")
    h.add_argument("--per-keyword", type=int)
    h.add_argument("--per-creator", type=int)
    h.add_argument("--price", type=float, help="actor price per 1,000 results in USD")
    h.add_argument("--dry-run", action="store_true", help="show the plan and cost, fetch nothing")
    h.add_argument("--force", action="store_true", help="run even if the estimate exceeds the free credit")
    sub.add_parser("usage", help="spend this month")

    for name, hlp in (("outliers", "step 2: viral outliers"), ("analyse", "step 3: why they won, and the winning formats")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--niche")
        p.add_argument("--days", type=int)
        p.add_argument("--k", type=float, help="how many times a creator's median counts as an outlier")
        p.add_argument("--k-followers", type=float)
        p.add_argument("--min-plays", type=int)
        p.add_argument("--out")
        if name == "analyse":
            p.add_argument("--top", type=int)

    c = sub.add_parser("compare-models", help="run the same stored Reels through two models and show where they disagree")
    c.add_argument("--a", default="claude-haiku-5-5")
    c.add_argument("--b", default="claude-sonnet-5-5")
    c.add_argument("--n", type=int, default=10)
    c.add_argument("--niche")

    s = sub.add_parser("script", help="step 4: write a script, or remix a Reel's structure")
    s.add_argument("--topic", required=True)
    s.add_argument("--niche")
    s.add_argument("--from-reel", help="Reel id (from `outliers`) whose structure to remix")
    s.add_argument("--angle")

    v = sub.add_parser("vault", help="step 5: your scripts").add_subparsers(dest="vault_cmd", required=True)
    for c in ("list", "search", "export"):
        p = v.add_parser(c)
        p.add_argument("--status", choices=STATUSES)
        p.add_argument("--niche")
        p.add_argument("--tag")
        if c == "search":
            p.add_argument("text")
        if c == "export":
            p.add_argument("--format", choices=["md", "csv", "json", "xlsx"], default="md")
            p.add_argument("--out")
    v.add_parser("stats")
    v.add_parser("show").add_argument("id", type=int)
    p = v.add_parser("status")
    p.add_argument("id", type=int)
    p.add_argument("value", choices=STATUSES)
    for c in ("tag", "untag"):
        p = v.add_parser(c)
        p.add_argument("id", type=int)
        p.add_argument("tags", nargs="+")
    p = v.add_parser("note")
    p.add_argument("id", type=int)
    p.add_argument("text")
    p = v.add_parser("delete")
    p.add_argument("id", type=int)
    p.add_argument("--yes", action="store_true")
    return ap


def main(argv=None, *, harvester=None, llm=None, niches_path=None, now=None) -> int:
    args = build_parser().parse_args(argv)
    load_env()
    vault = None
    try:
        niches = Niches(Path(niches_path)) if niches_path else Niches()
        if args.cmd == "niche":
            return cmd_niche(args, {"niches": niches})
        path = args.vault or (SAMPLE_VAULT if args.sample else None)
        vault = Vault(path) if path else Vault()
        ctx = {"niches": niches, "vault": vault, "sample": args.sample, "settings": load_json(ROOT / "config" / "settings.json"),
               "harvester": harvester, "now": now or utcnow(), "llm": llm}
        needs_llm = args.cmd in ("analyse", "script")
        if needs_llm and ctx["llm"] is None:
            if args.sample:
                from scouts.fake_llm import FakeLLM
                ctx["llm"] = FakeLLM()
            else:
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    raise UsageError("ANTHROPIC_API_KEY is missing. Put it in .env (see .env.example).")
                from scouts.llm import AnthropicLLM, model_for
                ctx["llm"] = AnthropicLLM(model_for("scripts" if args.cmd == "script" else "analysis", ctx["settings"]))
        handler = {"harvest": cmd_harvest, "usage": cmd_usage, "outliers": cmd_outliers, "analyse": cmd_analyse,
                   "script": cmd_script, "compare-models": cmd_compare, "vault": cmd_vault}[args.cmd]
        return handler(args, ctx)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    finally:
        if vault is not None:
            vault.close()


if __name__ == "__main__":
    sys.exit(main())
