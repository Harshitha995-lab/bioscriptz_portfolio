"""Topic outlier research: give a topic (any topic), get the top outlier Reels of the last N days, each decoded.

Pipeline: topic -> keywords -> harvest (budget-guarded) -> creators' own Reels as a baseline -> outliers -> top 10 -> breakdown -> decode.
Everything that can be decided in code (angle, rate of revelation, super hook, contrarian) is decided in code from the breakdown,
so it costs no extra model calls and cannot be invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import budget
from .common import Reel, utcnow
from .llm import LLM
from .niches import clean_keyword
from .outliers import Outlier, find_outliers
from .viral_analysis import ViralBreakdown, analyse_reels

MAX_TOPIC = 60
WORDS_PER_SECOND = 2.6
STAGE1_SHARE = 0.55            # share of a run's results spent on keyword search; the rest buys creators' own Reels as a baseline
BASELINE_CREATORS = 8
BASELINE_PER_CREATOR = 12


def clean_topic(raw: str) -> str:
    t = " ".join(str(raw or "").split())
    t = "".join(ch for ch in t if ch.isprintable())
    if not t:
        raise ValueError("Type a topic, for example: daily cosmetics")
    if len(t) > MAX_TOPIC:
        raise ValueError(f"Keep the topic under {MAX_TOPIC} characters.")
    return t


def default_keywords(topic: str) -> list[str]:
    t = topic.lower().strip()
    tag = re.sub(r"[^a-z0-9]", "", t)
    kws = [f"#{tag}"] if tag else []
    kws += [t, f"{t} tips", f"{t} mistakes", f"{t} myths", f"how to {t}"]
    return kws


def creator_queries(topic: str) -> list[str]:
    t = topic.lower().strip()
    return list(dict.fromkeys([t, f"{t} coach", f"{t} tips", f"{t} creator", f"{t} expert", f"{t} strategy"]))


TIERS = (("micro", 10_000), ("small", 100_000), ("big", None))
TIER_QUOTA = {"big": 4, "small": 3, "micro": 3}      # of the top 10 creators; leftovers fill from whoever is next
CREATOR_PER_QUERY = 25
MIN_FOLLOWERS = 1000          # name search also returns hobby and empty accounts; below these floors a creator says nothing about what works
MIN_MEDIAN_PLAYS = 1000


def tier(followers: int | None) -> str:
    """micro under 10,000 followers, small up to 100,000, big above. Unknown follower count counts as micro."""
    f = followers or 0
    for name, cap in TIERS:
        if cap is None or f < cap:
            return name
    return "big"


def profile_to_reels(profile: dict, topic: str) -> list[Reel]:
    """Video posts from a profile item's latestPosts. Pinned posts are dropped (they are old on purpose and skew a creator's 'usual'),
    as are posts by other accounts (collabs/tags)."""
    from .instagram_harvest import item_to_reel, to_int
    name = str(profile.get("username") or "").lower()
    followers = to_int(profile.get("followersCount")) or None
    out = []
    for post in profile.get("latestPosts") or []:
        if not isinstance(post, dict) or post.get("isPinned"):
            continue
        if str(post.get("ownerUsername") or name).lower() != name:
            continue
        is_video = post.get("type") == "Video" or post.get("productType") == "clips" or (
            post.get("type") not in ("Image", "Sidecar") and (post.get("videoUrl") or post.get("videoPlayCount")))
        if not is_video:
            continue
        r = item_to_reel(post, source="creator")
        if r is None:
            continue
        r.account, r.followers, r.niche = name, followers, topic
        out.append(r)
    return out


def plan_creators(topic: str, month_spent: float, price: float | None, max_run_usd: float) -> RunPlan:
    p = budget.ASSUMED_PRICE_PER_1000 if price is None else float(price)
    qs = creator_queries(topic)
    est = round(len(qs) * CREATOR_PER_QUERY / 1000 * p, 4)
    remaining = max(budget.FREE_CREDIT_USD - month_spent, 0.0)
    ok = est <= max(remaining - budget.RESERVE_USD, 0.0) + 1e-9 and est <= max_run_usd
    msg = "" if ok else f"This needs about ${est:.2f} but only ${max(remaining - budget.RESERVE_USD, 0.0):.2f} is available this month."
    return RunPlan(qs, CREATOR_PER_QUERY, 0, 0, p, price is None, est, ok, month_spent, msg)


def discover_creators(vault, topic: str, plan: RunPlan, apify_cfg: dict, token: str, discoverer, progress=lambda m: None, now=None) -> dict:
    """Find creators for a topic by user search, save their recent Reels (niche = topic) and the spend."""
    now = now or utcnow()
    if not plan.ok:
        raise RuntimeError(plan.message)
    remaining = max(budget.FREE_CREDIT_USD - vault.month_spend(now), 0.0)
    cap = budget.per_run_cap(min(remaining, plan.est_cost + budget.RESERVE_USD), len(plan.keywords))
    progress(f"Searching Instagram for creators ({len(plan.keywords)} searches)…")
    profiles, info = discoverer(plan.keywords, apify_cfg, token, per_query=plan.per_keyword, run_cap_usd=cap)
    reels = [r for p in profiles for r in profile_to_reels(p, topic)]
    vault.upsert_reels(reels, now)
    cost = info.get("usage_usd") if info.get("usage_usd") is not None else info.get("items", len(profiles)) / 1000 * plan.price
    vault.record_run("topic-creators", cost, info.get("items", len(profiles)),
                     f"{topic}; " + ("reported by Apify" if info.get("usage_usd") is not None else "ESTIMATED"), now)
    return {"creators": len(profiles), "reels": len(reels), "cost": round(cost, 4)}


def creator_board(vault, topic: str, top: int = 10) -> dict:
    """The topic's strongest creators from the saved Reels. Ranked by median plays within each size tier, so micro-creators
    are shown next to the big names instead of being buried by them."""
    by: dict[str, list[Reel]] = {}
    for r in vault.reels(topic):
        by.setdefault(r.account, []).append(r)
    rows = []
    for name, rs in by.items():
        plays = sorted(r.plays for r in rs)
        best = max(rs, key=lambda r: r.plays)
        f = next((r.followers for r in rs if r.followers), None)
        med = plays[len(plays) // 2]
        rows.append({"username": name, "followers": f, "tier": tier(f), "reels": len(rs), "median_plays": med, "best_plays": best.plays,
                     "best_link": best.url, "reach": round(med / f, 2) if f else None})
    found_all = len(rows)
    rows = [r for r in rows if r["reels"] >= 3 and (r["followers"] or 0) >= MIN_FOLLOWERS and r["median_plays"] >= MIN_MEDIAN_PLAYS]
    rows.sort(key=lambda r: -r["median_plays"])
    chosen = []
    for t, q in TIER_QUOTA.items():
        chosen += [r for r in rows if r["tier"] == t][:q]
    chosen += [r for r in rows if r not in chosen][:max(top - len(chosen), 0)]
    chosen = sorted(chosen, key=lambda r: -r["median_plays"])[:top]
    return {"creators": chosen, "found": len(rows), "searched": found_all, "tiers": {t: sum(1 for r in rows if r["tier"] == t) for t, _ in TIERS},
            "note": "Ranked by median plays of their recent Reels (the usual, not one lucky post). Followers come from Instagram at fetch time."}


def brand_keywords(brand: str, category: str) -> list[str]:
    """Searches aimed at one brand. The category separates a brand from the ordinary word (Minimalist the skincare brand vs minimalism)."""
    b, c = brand.lower().strip(), category.lower().strip()
    tag = re.sub(r"[^a-z0-9]", "", b)
    kws = [f"{b} {c}", f"{b} review", f"{b} vs", f"{b} results", f"{c} {b}"]
    if tag:
        kws.insert(0, f"#{tag}{re.sub(r'[^a-z0-9]', '', c)}")
    return list(dict.fromkeys(kws))


HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def clean_brand(raw: dict) -> dict:
    """Validate the Brand mode fields from the web form."""
    def one(v, what, limit):
        v = " ".join(str(v or "").split())
        if not v or len(v) > limit or not all(ch.isprintable() for ch in v):
            raise ValueError(f"{what} is required (up to {limit} characters).")
        return v
    brand, category = one(raw.get("brand"), "Brand name", 40), one(raw.get("category"), "Category", 40)

    def handle(h):
        h = str(h or "").strip().lstrip("@").lower()
        if h and not HANDLE.match(h):
            raise ValueError(f"'{h}' is not a valid Instagram handle.")
        return h
    own = handle(raw.get("own"))
    comp = [handle(x) for x in (raw.get("competitors") or [])][:3]
    return {"brand": brand, "category": category, "own": own, "competitors": [c for c in comp if c and c != own]}


def expand_keywords(topic: str, llm: LLM | None) -> list[str]:
    """The fixed patterns above, plus up to 4 searches a model suggests. A model failure falls back to the fixed ones."""
    kws = default_keywords(topic)
    if llm is None:
        return kws
    try:
        resp = llm.complete_json("You suggest Instagram search terms. Reply as JSON: {\"keywords\": [up to 4 short search phrases or #hashtags "
                                 "that people use for posts on this topic, different angles of it]}.", f"Topic: {topic}")
        for k in resp.get("keywords", [])[:4]:
            k = clean_keyword(str(k))
            if k and len(k) <= 60 and k.lower() not in {x.lower() for x in kws}:
                kws.append(k)
    except Exception:
        pass
    return kws


# ---------------------------------------------------------------------------- budget for one research run
@dataclass
class RunPlan:
    keywords: list
    per_keyword: int
    baseline_creators: int
    per_creator: int
    price: float
    price_assumed: bool
    est_cost: float
    ok: bool
    month_spent: float
    message: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def plan_run(keywords: list[str], month_spent: float, price: float | None, max_run_usd: float, extra_creators: int = 0) -> RunPlan:
    p = budget.ASSUMED_PRICE_PER_1000 if price is None else float(price)
    remaining = max(budget.FREE_CREDIT_USD - month_spent, 0.0)
    total = budget.affordable_results(min(remaining, max_run_usd + budget.RESERVE_USD), p)
    s1 = int(total * STAGE1_SHARE)
    per_kw = s1 // len(keywords) if keywords else 0
    s2 = total - per_kw * len(keywords)
    n_cr = min(BASELINE_CREATORS + extra_creators, s2 // BASELINE_PER_CREATOR)       # extras: the brand's own and competitor handles
    plan = budget.make_plan(len(keywords), n_cr, per_kw, BASELINE_PER_CREATOR if n_cr else 0, price)
    ok, _, msg = budget.check(plan, month_spent)
    if per_kw < 5:
        ok, msg = False, "Not enough free credit left this month for a useful search. " + msg
    return RunPlan(keywords, per_kw, n_cr, plan.per_creator, p, price is None, plan.est_cost, ok, month_spent, msg)


def pick_baseline_creators(reels: list[Reel], n: int) -> list[str]:
    """Creators behind the best recent keyword hits (by reach for their size), whose own Reels will give each a 'usual'."""
    best: dict[str, float] = {}
    for r in reels:
        score = r.plays / max(r.followers or 0, 1000)
        best[r.account] = max(best.get(r.account, 0.0), score)
    return [a for a, _ in sorted(best.items(), key=lambda kv: -kv[1])[:n]]


# ---------------------------------------------------------------------------- decoding (all in code)
def content_angle(bd: ViralBreakdown) -> str:
    types = {bd.hooks[c]["type"] for c in ("audio", "text") if bd.hooks.get(c, {}).get("analysed")}
    loop, spice = bd.loop.get("type"), set(bd.spice)
    if loop == "myth-bust" or "contrarian" in types:
        return "Contrarian / myth-bust"
    if loop == "before-after":
        return "Proof / before-after"
    if loop == "countdown-list" or "number-list" in types:
        return "List / how-to"
    if loop == "problem-solution":
        return "Problem → solution"
    if types & {"story-start", "confession"}:
        return "Story / confession"
    if "demonstration" in spice:
        return "Demonstration"
    if loop in ("mystery-reveal", "curiosity-gap") or "curiosity-gap" in types:
        return "Curiosity / reveal"
    return "General explainer"


def rate_of_revelation(bd: ViralBreakdown, reel: Reel) -> dict:
    """New-information beats per 10 seconds. Length comes from the video, or else from the transcript at a normal speaking pace."""
    reveals = sum(1 for b in bd.structure if b["beat"] not in ("hook", "setup", "cta"))
    if reel.duration_s:
        secs, basis = float(reel.duration_s), "video length"
    elif reel.transcript:
        secs, basis = max(len(reel.transcript.split()) / WORDS_PER_SECOND, 1.0), "estimated from transcript length"
    else:
        return {"reveals": reveals, "per_10s": None, "seconds": None, "basis": "no length known", "pace": "unknown"}
    rate = reveals / secs * 10
    pace = "fast" if rate >= 3 else "medium" if rate >= 1.5 else "slow"       # rough bands, only for skimming
    return {"reveals": reveals, "per_10s": round(rate, 1), "seconds": round(secs), "basis": basis, "pace": pace}


def super_hook(bd: ViralBreakdown) -> dict:
    """Spoken, on-screen and visual hooks all present AND working together."""
    present = {c: (bd.hooks[c]["analysed"] and bd.hooks[c]["type"] != "none") for c in ("audio", "text", "video")}
    unseen = [c for c in ("text", "video") if not bd.hooks[c]["analysed"]]
    if unseen:
        return {"value": "unknown", "why": "needs video frames to judge the on-screen text and visual hook", "present": present}
    if all(present.values()):
        if bd.hooks_aligned:
            return {"value": "yes", "why": "spoken, text and visual hooks are all present and say the same thing", "present": present}
        return {"value": "no", "why": "all three hooks are present but they do not line up", "present": present}
    return {"value": "no", "why": "missing: " + ", ".join(c for c, ok in present.items() if not ok), "present": present}


def contrarian_take(bd: ViralBreakdown) -> dict:
    why = []
    for c in ("audio", "text"):
        h = bd.hooks.get(c, {})
        if h.get("analysed") and h.get("type") == "contrarian":
            why.append(f"{c} hook is contrarian")
    if bd.loop.get("type") == "myth-bust":
        why.append("story is a myth-bust")
    why += [f"spice: {s}" for s in bd.spice if s in ("controversy", "named-enemy")]
    a = bd.hooks.get("audio", {})
    quote = a.get("text", "") if a.get("analysed") and a.get("verified_quote") else ""
    return {"value": bool(why), "why": why, "quote": quote if why else ""}


def decode(outlier: Outlier, bd: ViralBreakdown) -> dict:
    r = outlier.reel
    base = {"reel_id": r.id, "creator": r.account, "followers": r.followers, "link": r.url, "plays": r.plays, "likes": r.likes,
            "comments": r.comments, "tier": tier(r.followers) if r.followers else None, "ratio": round(outlier.ratio, 1), "strong": outlier.strong,
            "basis": f"{outlier.ratio:.0f}× this creator's usual {outlier.usual:,.0f} plays" if outlier.strong
            else (f"{outlier.ratio:.0f}× their follower count (no creator baseline yet; treat as a lead)" if outlier.basis == "followers"
                  else f"{outlier.ratio:.0f}× the typical Reel in this search (no creator baseline or follower count; treat as a lead)"),
            "posted_at": r.posted_at.isoformat() if r.posted_at else None, "keyword": r.keyword}
    if bd.error:
        return {**base, "error": bd.error}
    h = bd.hooks
    return {**base, "error": "",
            "hook": {"audio": {k: h["audio"].get(k) for k in ("analysed", "text", "type", "verified_quote")},
                     "text": {k: h["text"].get(k) for k in ("analysed", "text", "type")},
                     "video": {k: h["video"].get(k) for k in ("analysed", "description", "type")}},
            "content_angle": content_angle(bd), "rate_of_revelation": rate_of_revelation(bd, r), "super_hook": super_hook(bd),
            "contrarian": contrarian_take(bd),
            "cta": {"type": bd.cta.get("type", "none"), "text": bd.cta.get("text", "")},
            "format": bd.format, "story_loop": bd.loop.get("type"), "structure": [b["beat"] for b in bd.structure],
            "spice": bd.spice, "evidence": bd.evidence}


MIN_PATTERN = 3        # fewer Reels than this in a group is not a pattern


def winning_formats(cards: list[dict]) -> dict:
    """What the decoded top Reels do, grouped by creator size. A format = content angle + the kind of spoken hook.
    Descriptive only: it lists what winners share; it does not prove those choices caused the views (that needs ordinary
    Reels from the same creators for comparison: `agent.py analyse`)."""
    groups: dict[str, list[dict]] = {}
    for c in cards:
        if c.get("error"):
            continue
        for key in ("all", c.get("tier") or "unknown size"):
            groups.setdefault(key, []).append(c)
    out = []
    for name in ("all", "micro", "small", "big", "unknown size"):
        cs = groups.get(name)
        if not cs:
            continue
        formats: dict[tuple, list[dict]] = {}
        for c in cs:
            ht = c["hook"]["audio"]["type"] if c["hook"]["audio"]["analysed"] else "no transcript"
            formats.setdefault((c["content_angle"], ht), []).append(c)
        rows = []
        for (angle, ht), members in sorted(formats.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            best = max(members, key=lambda c: c["ratio"])
            rows.append({"angle": angle, "spoken_hook": ht, "count": len(members), "example_creator": best["creator"], "example_link": best["link"],
                         "example_structure": best["structure"]})
        rates = sorted(c["rate_of_revelation"]["per_10s"] for c in cs if c["rate_of_revelation"]["per_10s"] is not None)
        out.append({"group": name, "n": len(cs), "enough": len(cs) >= MIN_PATTERN, "formats": rows[:5],
                    "with_cta": sum(c["cta"]["type"] != "none" for c in cs), "contrarian": sum(c["contrarian"]["value"] for c in cs),
                    "median_rate": rates[len(rates) // 2] if rates else None})
    return {"groups": out, "min_pattern": MIN_PATTERN,
            "note": "Descriptive: what these winning Reels have in common. Groups under 3 Reels are shown but are not patterns."}


def summarise(cards: list[dict]) -> dict:
    ok = [c for c in cards if not c.get("error")]
    n = len(ok)
    if not n:
        return {"n": 0}
    angles: dict[str, int] = {}
    for c in ok:
        angles[c["content_angle"]] = angles.get(c["content_angle"], 0) + 1
    rates = [c["rate_of_revelation"]["per_10s"] for c in ok if c["rate_of_revelation"]["per_10s"] is not None]
    return {"n": n, "angles": sorted(angles.items(), key=lambda kv: -kv[1]),
            "contrarian": sum(c["contrarian"]["value"] for c in ok), "super_hook_yes": sum(c["super_hook"]["value"] == "yes" for c in ok),
            "super_hook_known": sum(c["super_hook"]["value"] != "unknown" for c in ok),
            "with_cta": sum(c["cta"]["type"] != "none" for c in ok),
            "median_rate": sorted(rates)[len(rates) // 2] if rates else None,
            "note": "Descriptive only: these are what the top Reels have in common, not proof that any of it caused the views."}


# ---------------------------------------------------------------------------- the run
def decode_top(vault, topic: str, llm: LLM, vocab: dict, *, days: int = 7, top: int = 10, frames=None, transcriber=None,
               min_plays: int = 1000, now=None, settings: dict | None = None, brand: dict | None = None, creators: bool = False) -> dict:
    from .transcribe import ensure_transcripts
    t = (settings or {}).get("outliers", {})
    reels = vault.reels()
    outs, stats = find_outliers(reels, niche=topic, days=days, min_plays=min_plays, k_usual=t.get("k_usual", 3.0),
                                k_followers=t.get("k_followers", 5.0), min_reels=t.get("min_reels_for_usual", 5), usual_days=t.get("usual_days", 180), now=now)
    chosen = outs[:top]
    tstats = ensure_transcripts([o.reel for o in chosen], transcriber)
    for o in chosen:
        if o.reel.transcript:
            vault.set_transcript(o.reel.id, o.reel.transcript)
    cached = vault.breakdowns([o.reel.id for o in chosen])
    fresh = analyse_reels([o.reel for o in chosen if o.reel.id not in cached], llm, vocab, frames)
    for bd in fresh.values():
        vault.save_breakdown(bd)
    bds = {**cached, **fresh}
    cards = [decode(o, bds[o.reel.id]) for o in chosen]
    cards.sort(key=lambda c: (not c["strong"], -c["ratio"]))
    audience = None
    if brand is not None:
        ignore = {w for w in re.split(r"\W+", (brand["brand"] + " " + brand["category"]).lower()) if w} | {re.sub(r"[^a-z0-9]", "", brand["brand"].lower())}
        audience = audience_section(vault, topic, llm, ignore | {brand["own"], *brand["competitors"]} - {""})
    board = creator_board(vault, topic) if creators else None
    return {"brand": brand, "audience": audience, "creator_board": board, "formats": winning_formats(cards) if creators else None, "topic": topic, "days": days, "generated_at": (now or utcnow()).isoformat(), "stats": stats, "cards": cards,
            "summary": summarise(cards), "transcripts": tstats,
            "frames": any("frames" in b.evidence for b in bds.values() if not b.error),
            "undated": sum(1 for o in chosen if o.reel.posted_at is None)}


def harvest_topic(vault, topic: str, plan: RunPlan, apify_cfg: dict, token: str, harvester, progress=lambda m: None, now=None,
                  priority_creators: list[str] | None = None) -> dict:
    """Stage 1: keyword search. Stage 2: the best hits' creators' own recent Reels, so each has a 'usual'. Spend is recorded per stage."""
    now = now or utcnow()
    spent = {"stage1": 0.0, "stage2": 0.0}
    if not plan.ok:
        raise RuntimeError(plan.message)
    remaining = max(budget.FREE_CREDIT_USD - vault.month_spend(now), 0.0)
    cap = budget.per_run_cap(min(remaining, plan.est_cost + budget.RESERVE_USD), len(plan.keywords) + 1)
    progress(f"Searching Instagram for {len(plan.keywords)} search terms…")
    found, info = harvester(plan.keywords, apify_cfg, token, None, [], per_keyword=plan.per_keyword, per_creator=0, run_cap_usd=cap)
    for r in found:
        r.niche = topic
    vault.upsert_reels(found, now)
    est1 = len(found) / 1000 * plan.price
    spent["stage1"] = info.get("usage_usd") if info.get("usage_usd") is not None else est1
    vault.record_run("topic-search", spent["stage1"], len(found),
                     f"{topic}; " + ("reported by Apify" if info.get("usage_usd") is not None else "ESTIMATED"), now)
    got2 = 0
    if plan.baseline_creators and (found or priority_creators):
        priority = [c.lower() for c in (priority_creators or [])]
        creators = (priority + [c for c in pick_baseline_creators(found, plan.baseline_creators) if c.lower() not in priority])[:plan.baseline_creators]
        # the plan is re-checked against what is really left, because stage 1 may have cost more than estimated
        left = max(budget.FREE_CREDIT_USD - vault.month_spend(now), 0.0)
        affordable = budget.affordable_results(left, plan.price)
        n = min(len(creators), affordable // plan.per_creator)
        if n:
            progress(f"Fetching recent Reels of the {n} strongest creators to learn what is normal for each…")
            try:
                base, info2 = harvester([], apify_cfg, token, None, creators[:n], per_keyword=0, per_creator=plan.per_creator,
                                        run_cap_usd=budget.per_run_cap(left, 1))
            except Exception as exc:        # e.g. the actor is blocked on profiles: keep stage 1, outliers will just be 'weak'
                base, info2, note = [], {}, f"{type(exc).__name__}: {exc}"
                progress("Creator baselines could not be fetched; outliers will be judged against follower count only.")
            for r in base:
                if r.account.lower() in priority:
                    r.niche = topic                    # the brand's and its competitors' own Reels are on-topic by definition
            vault.upsert_reels(base, now)           # niche stays blank for everyone else: they are a baseline, not candidates
            got2 = len(base)
            spent["stage2"] = info2.get("usage_usd") if info2.get("usage_usd") is not None else got2 / 1000 * plan.price
            vault.record_run("topic-baseline", spent["stage2"], got2,
                             f"{topic}; " + ("reported by Apify" if info2.get("usage_usd") is not None else "ESTIMATED"), now)
            if not got2 and info2.get("creators_skipped"):
                progress("Creator baselines skipped: " + info2["creators_skipped"] + ". Outliers are judged against the typical Reel in the search.")
            elif not got2:
                progress("The baseline fetch returned no Reels (this actor reported limited profile scraping). Outliers will be weak leads.")
    return {"keyword_reels": len(found), "baseline_reels": got2, "cost": round(sum(spent.values()), 4)}


def live_media():
    """(frames provider or None, transcriber, warning). Frames need ffmpeg; without them text/visual hooks are reported as not analysed."""
    from .frames import FfmpegFrames, ffmpeg_available
    from .transcribe import FasterWhisperTranscriber, LazyTranscriber
    frames = FfmpegFrames() if ffmpeg_available() else None
    warn = "" if frames else "ffmpeg is not installed, so on-screen text, visual hooks, format and pacing could not be analysed."
    return frames, LazyTranscriber(FasterWhisperTranscriber), warn


COMPARE_FIELDS = {"spoken hook type": lambda b: b.hooks["audio"]["type"], "story loop": lambda b: b.loop.get("type"),
                  "CTA type": lambda b: b.cta.get("type"), "contrarian": lambda b: contrarian_take(b)["value"],
                  "content angle": content_angle, "on-screen hook type": lambda b: b.hooks["text"]["type"],
                  "format": lambda b: b.format}


def compare_models(reels: list[Reel], llm_a: LLM, llm_b: LLM, vocab: dict, frames=None) -> dict:
    """Same Reels through two models, nothing saved. Agreement is NOT accuracy: it shows where they differ, so you can read those Reels yourself."""
    a, b = analyse_reels(reels, llm_a, vocab, frames), analyse_reels(reels, llm_b, vocab, frames)
    fields, diffs = {}, []
    both = [r for r in reels if not a[r.id].error and not b[r.id].error]
    for name, fn in COMPARE_FIELDS.items():
        same = 0
        for r in both:
            x, y = fn(a[r.id]), fn(b[r.id])
            same += x == y
            if x != y:
                diffs.append({"reel": r.url, "field": name, "a": x, "b": y})
        fields[name] = {"agree": same, "of": len(both)}
    return {"reels": len(reels), "both_ok": len(both), "failed_a": sum(bool(x.error) for x in a.values()),
            "failed_b": sum(bool(x.error) for x in b.values()), "fields": fields, "differences": diffs}


SAMPLE_COMMENTS = ["How much does this cost? Is it worth it?", "Love this so much, best advice I have seen", "Where can I buy it? Need this!",
                   "Tried something like this and it stopped working after a week", "Is it better than the other brand?", "wow", "Can you make a video on the basics?",
                   "Honestly the price is too high for what you get"]


def add_sample_audience(reels: list[Reel]) -> None:
    """Synthetic comments and mentions so sample mode can show the audience section. Not real data."""
    for i, r in enumerate(reels):
        r.extras = {"comments": [SAMPLE_COMMENTS[(i + k) % len(SAMPLE_COMMENTS)] for k in range(3)], "mentions": ["sample_brand_x"] if i % 3 == 0 else [],
                    "tagged": ["sample_rival_y"] if i % 4 == 0 else [], "hashtags": ["sample", "skincare" if i % 2 else "routine"]}


def audience_section(vault, topic: str, llm: LLM, ignore: set[str]) -> dict:
    from .customer import collect, mention_signals, voice_of_customer
    reels = vault.reels(topic)
    pairs = collect(reels)
    out = {"reels": len(reels), "signals": mention_signals(reels, ignore)}
    out["voice"] = voice_of_customer(llm, pairs) if pairs else {"comments": 0, "themes": [], "errors": [], "sorted": 0, "reactions": 0, "caveat": ""}
    return out
