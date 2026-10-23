"""Step 1: pull Reels from Apify and map them into Reel objects.

The Apify actor is chosen in config/apify.json. Actors name their fields differently, so
item_to_reel() tries several common names per field (extend them with "field_map" in the
config). On a first live run, check out/<week>/raw_sample.json against the mapping.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from .common import Reel, parse_datetime

FIELD_CANDIDATES = {
    "id": ["id", "shortCode", "code", "pk"],
    "url": ["url", "permalink", "postUrl", "link"],
    "account": ["ownerUsername", "username", "owner.username", "author", "accountName"],
    "followers": ["ownerFollowersCount", "followersCount", "followers", "owner.followersCount"],
    "caption": ["caption", "text", "description"],
    "transcript": ["transcript", "transcription", "videoTranscript"],
    "plays": ["videoPlayCount", "playsCount", "playCount", "viewCount", "videoViewCount", "views"],
    "likes": ["likesCount", "likeCount", "likes"],
    "comments": ["commentsCount", "commentCount", "comments"],
    "keyword": ["searchTerm", "hashtag", "query"],
    "video": ["videoUrl", "video_url", "videoUrlHd", "videoPlayUrl"],
    "duration": ["videoDuration", "duration", "videoDurationSeconds"],
    "posted": ["timestamp", "takenAt", "taken_at", "postedAt", "date", "createdAt"],
}


def get_path(item: dict, path: str):
    cur = item
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def first(item: dict, candidates: list[str]):
    for c in candidates:
        v = get_path(item, c)
        if v not in (None, ""):
            return v
    return None


def to_int(value) -> int:
    """Counts as non-negative ints. Instagram reports hidden like counts as -1; that becomes 0."""
    try:
        return max(int(float(value)), 0)
    except (TypeError, ValueError):
        return 0


def to_float(value) -> float | None:
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def item_extras(item: dict) -> dict:
    """What the audience said and who was mentioned. Kept small: up to 20 comments of 300 characters."""
    def names(key):
        return [str(x.get("username") if isinstance(x, dict) else x).lower() for x in (item.get(key) or []) if x][:20]
    comments = []
    for c in item.get("latestComments") or []:
        t = str((c.get("text") if isinstance(c, dict) else c) or "").strip()
        if t:
            comments.append(t[:300])
    out = {"comments": comments[:20], "mentions": names("mentions"), "tagged": names("taggedUsers"),
           "hashtags": [str(h).lower() for h in (item.get("hashtags") or [])][:30]}
    return {k: v for k, v in out.items() if v}


def item_to_reel(item: dict, field_map: dict | None = None, source: str = "") -> Reel | None:
    fm = {**FIELD_CANDIDATES, **(field_map or {})}
    rid, url = first(item, fm["id"]), first(item, fm["url"])
    if not rid and not url:
        return None
    rid = str(rid or url)
    url = str(url or f"https://www.instagram.com/reel/{rid}/")
    followers = first(item, fm["followers"])
    caption = first(item, fm["caption"])
    transcript = first(item, fm["transcript"])
    extras = item_extras(item)
    return Reel(
        id=rid,
        url=url,
        account=str(first(item, fm["account"]) or "unknown"),
        caption=str(caption or ""),
        transcript=str(transcript or ""),
        followers=to_int(followers) if followers is not None else None,
        plays=to_int(first(item, fm["plays"])),
        likes=to_int(first(item, fm["likes"])),
        comments=to_int(first(item, fm["comments"])),
        posted_at=parse_datetime(first(item, fm["posted"])),
        keyword=str(first(item, fm["keyword"]) or ""),
        video_url=str(first(item, fm["video"]) or ""),
        duration_s=to_float(first(item, fm["duration"])),
        source=source,
        extras=extras,
    )


def split_keywords(lines: list[str]) -> tuple[list[str], list[str]]:
    """Hashtags (lines starting with #, returned without it) and plain search terms."""
    hashtags = [l.lstrip("#") for l in lines if l.startswith("#")]
    terms = [l for l in lines if not l.startswith("#")]
    return hashtags, terms


def tag_url(keyword: str) -> str:
    """Instagram hashtag page for a keyword: spaces and punctuation dropped, as hashtags are one word."""
    tag = re.sub(r"[\W_]+", "", keyword.lstrip("#").lower())
    return f"https://www.instagram.com/explore/tags/{quote(tag)}/" if tag else ""


def profile_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle.strip().lstrip('@')}/"


def render_template(obj, subs: dict):
    """Fill {hashtags} / {terms} placeholders in the actor input template."""
    if isinstance(obj, str):
        return subs.get(obj, obj)
    if isinstance(obj, list):
        out = []
        for x in obj:
            v = render_template(x, subs)
            if isinstance(x, str) and x in subs and isinstance(v, list):
                out.extend(v)
            else:
                out.append(v)
        return out
    if isinstance(obj, dict):
        return {k: render_template(v, subs) for k, v in obj.items()}
    return obj


def _call(actor, run_input: dict, max_charge_usd: float | None):
    """Start an actor run, asking Apify to stop at max_charge_usd if this client version supports it."""
    import inspect

    kwargs = {"run_input": run_input}
    try:
        if max_charge_usd and "max_total_charge_usd" in inspect.signature(actor.call).parameters:
            kwargs["max_total_charge_usd"] = max_charge_usd
    except (TypeError, ValueError):
        pass
    return actor.call(**kwargs)


def run_field(run, camel: str, snake: str):
    """A field of an Apify run. Older apify-client versions return a dict, newer ones a Run object with snake_case attributes."""
    if isinstance(run, dict):
        return run.get(camel, run.get(snake))
    for name in (snake, camel):
        if hasattr(run, name):
            return getattr(run, name)
    if hasattr(run, "model_dump"):
        d = run.model_dump(by_alias=False)
        return d.get(snake, d.get(camel))
    return None


def _run_actor(client, actor_id: str, run_input: dict, field_map, source: str, limit: int | None, keyword: str = "",
               max_charge_usd: float | None = None):
    run = _call(client.actor(actor_id), run_input, max_charge_usd)
    if not run:
        raise RuntimeError(f"Apify run for {actor_id} returned nothing; check the run in the Apify console.")
    reels, raw_sample, items, skipped = [], [], 0, 0
    dataset_id = run_field(run, "defaultDatasetId", "default_dataset_id")
    if not dataset_id:
        raise RuntimeError(f"Apify run for {actor_id} gave no dataset id; check the run in the Apify console.")
    for item in client.dataset(dataset_id).iterate_items():
        items += 1
        if len(raw_sample) < 3:
            raw_sample.append(item)
        reel = item_to_reel(item, field_map, source=source)
        if reel is None:
            skipped += 1
            continue
        if keyword:
            reel.keyword = keyword   # we know it because this run searched for exactly one keyword
        reels.append(reel)
        if limit and len(reels) >= limit:
            break
    usage = run_field(run, "usageTotalUsd", "usage_total_usd")
    try:
        usage = float(usage) if usage is not None else None       # may be a Decimal in newer clients
    except (TypeError, ValueError):
        usage = None
    return reels, {"items": items, "skipped": skipped, "raw_sample": raw_sample, "usage_usd": usage}


def clean_handles(lines: list[str]) -> list[str]:
    return [l.strip().lstrip("@") for l in lines if l.strip()]


def _limited(template: dict, limit: int | None) -> dict:
    t = dict(template)
    if limit and "resultsLimit" in t:
        t["resultsLimit"] = limit
    return t


def harvest(keyword_lines: list[str], cfg: dict, token: str, max_reels: int | None = None,
            creators: list[str] | None = None, *, per_keyword: int | None = None, per_creator: int | None = None,
            run_cap_usd: float | None = None) -> tuple[list[Reel], dict]:
    """Creators' recent Reels first (they also give each account a 'usual' level to compare against),
    then keyword/hashtag Reels fill the rest of max_reels."""
    if cfg.get("actor_id", "REPLACE_ME") == "REPLACE_ME":
        raise RuntimeError("Set actor_id in config/apify.json before a live run (see its _notes).")
    handles = clean_handles(creators or [])
    if handles and cfg.get("profile_actor_id", "REPLACE_ME") == "REPLACE_ME":
        raise RuntimeError("config/creators.txt lists accounts, but profile_actor_id is not set in "
                           "config/apify.json. Set it, or leave creators.txt empty.")
    from apify_client import ApifyClient  # lazy import: only needed for live runs

    client = ApifyClient(token)
    field_map = cfg.get("field_map")
    reels: list[Reel] = []
    info: dict = {"creator_accounts": len(handles), "items": 0, "skipped": 0}
    raw_sample: list = []

    if handles and cfg.get("profile_verified") is False:
        info["creators_skipped"] = "profile scraping of this actor has not been verified (profile_verified is false in config/apify.json)"
        handles = []
    if handles:
        run_input = render_template(_limited(cfg.get("profile_input_template", {}), per_creator), {"{usernames}": handles, "{profile_urls}": [profile_url(h) for h in handles]})
        got, meta = _run_actor(client, cfg["profile_actor_id"], run_input, field_map, "creator", max_reels, max_charge_usd=run_cap_usd)
        reels += got
        raw_sample += meta.pop("raw_sample")
        info["creators"] = meta
        info["items"] += meta["items"]
        info["skipped"] += meta["skipped"]

    remaining = None if not max_reels else max(max_reels - len(reels), 0)
    if remaining != 0:
        hashtags, terms = split_keywords(keyword_lines)
        if cfg.get("per_keyword_runs"):
            # One actor run per keyword, so every Reel is tagged with the keyword that found it. This is what
            # lets the library spread across different keywords. More runs, same cost per result.
            jobs = [("#" + h, [h], []) for h in hashtags] + [(t, [], [t]) for t in terms]

            def one(job):
                label, hs_, ts_ = job
                run_input = render_template(_limited(cfg.get("input_template", {}), per_keyword), {"{hashtags}": hs_, "{terms}": ts_,
                                                                                                             "{hashtag_urls}": [u for u in map(tag_url, hs_ + ts_) if u]})
                return _run_actor(client, cfg["actor_id"], run_input, field_map, "keyword", None, keyword=label.lstrip("#"),
                                  max_charge_usd=run_cap_usd)

            with ThreadPoolExecutor(max_workers=cfg.get("parallel_runs", 4)) as pool:
                outcomes = list(pool.map(one, jobs))
            meta = {"items": 0, "skipped": 0, "runs": len(jobs), "usage_usd": None}
            for got, m in outcomes:
                reels += got
                raw_sample += m["raw_sample"][:1]
                meta["items"] += m["items"]
                meta["skipped"] += m["skipped"]
                if m["usage_usd"] is not None:
                    meta["usage_usd"] = (meta["usage_usd"] or 0.0) + m["usage_usd"]
            if max_reels:
                reels = reels[:max_reels]   # creators come first, so they are never the ones cut
        else:
            run_input = render_template(_limited(cfg.get("input_template", {}), per_keyword), {"{hashtags}": hashtags, "{terms}": terms})
            got, meta = _run_actor(client, cfg["actor_id"], run_input, field_map, "keyword", remaining, max_charge_usd=run_cap_usd)
            reels += got
            raw_sample += meta.pop("raw_sample")
        info["keywords"] = meta
        info["items"] += meta["items"]
        info["skipped"] += meta["skipped"]
    usages = [info[k]["usage_usd"] for k in ("creators", "keywords") if k in info and info[k].get("usage_usd") is not None]
    info["usage_usd"] = sum(usages) if usages else None      # None = Apify did not report it; the caller falls back to the estimate
    info["raw_sample"] = raw_sample
    return reels, info


def harvest_profiles(usernames: list[str], cfg: dict, token: str, per_account: int | None = None) -> tuple[list[Reel], dict]:
    """Recent Reels of specific accounts. Used to look for a winner's earlier versions of the same topic."""
    handles = clean_handles(usernames)
    if not handles:
        return [], {"items": 0, "skipped": 0}
    if cfg.get("profile_actor_id", "REPLACE_ME") == "REPLACE_ME":
        raise RuntimeError("profile_actor_id is not set in config/apify.json, so followers' earlier Reels cannot be fetched.")
    from apify_client import ApifyClient

    template = dict(cfg.get("profile_input_template", {}))
    if per_account and "resultsLimit" in template:
        template["resultsLimit"] = per_account
    run_input = render_template(template, {"{usernames}": handles, "{profile_urls}": [profile_url(h) for h in handles]})
    reels, meta = _run_actor(ApifyClient(token), cfg["profile_actor_id"], run_input, cfg.get("field_map"), "followup", None)
    meta.pop("raw_sample", None)
    return reels, meta


def harvest_creators(queries: list[str], cfg: dict, token: str, per_query: int = 10, run_cap_usd: float | None = None) -> tuple[list[dict], dict]:
    """Instagram user search: one run per query. Each result is a profile (followers, bio) that already carries its latest posts,
    so finding creators and reading their recent Reels is one charge per creator. Returns profiles de-duplicated by username."""
    queries = [q.strip() for q in queries if q.strip()]
    if not queries:
        return [], {"items": 0, "runs": 0, "usage_usd": None}
    actor = cfg.get("profile_actor_id") or cfg.get("actor_id", "REPLACE_ME")
    if actor == "REPLACE_ME":
        raise RuntimeError("Set actor_id in config/apify.json before a live run.")
    from apify_client import ApifyClient

    client = ApifyClient(token)

    def one(q):
        run_input = {"addParentData": False, "search": q, "searchType": "user", "searchLimit": per_query, "resultsType": "details"}
        run = _call(client.actor(actor), run_input, run_cap_usd)
        if not run:
            raise RuntimeError(f"Apify run for {actor} returned nothing; check the run in the Apify console.")
        dataset_id = run_field(run, "defaultDatasetId", "default_dataset_id")
        if not dataset_id:
            raise RuntimeError(f"Apify run for {actor} gave no dataset id; check the run in the Apify console.")
        usage = run_field(run, "usageTotalUsd", "usage_total_usd")
        try:
            usage = float(usage) if usage is not None else None
        except (TypeError, ValueError):
            usage = None
        return [dict(i) for i in client.dataset(dataset_id).iterate_items()], usage

    with ThreadPoolExecutor(max_workers=cfg.get("parallel_runs", 4)) as pool:
        outcomes = list(pool.map(one, queries))
    seen: dict[str, dict] = {}
    items, usage = 0, None
    for got, u in outcomes:
        items += len(got)
        if u is not None:
            usage = (usage or 0.0) + u
        for p in got:
            name = str(p.get("username") or "").lower()
            if name and name not in seen:
                seen[name] = p
    return list(seen.values()), {"items": items, "runs": len(queries), "usage_usd": usage}


def harvest_profile_details(handles: list[str], cfg: dict, token: str, run_cap_usd: float | None = None) -> tuple[list[dict], dict]:
    """Profile details (followers, latest posts) for known handles: the creators behind winning hashtag Reels, and the ones the user names.
    One run, one charge per profile."""
    handles = clean_handles(handles)
    if not handles:
        return [], {"items": 0, "usage_usd": None}
    actor = cfg.get("profile_actor_id") or cfg.get("actor_id", "REPLACE_ME")
    if actor == "REPLACE_ME":
        raise RuntimeError("Set actor_id in config/apify.json before a live run.")
    from apify_client import ApifyClient

    client = ApifyClient(token)
    run = _call(client.actor(actor), {"directUrls": [profile_url(h) for h in handles], "resultsType": "details", "resultsLimit": 1,
                                      "addParentData": False}, run_cap_usd)
    if not run:
        raise RuntimeError(f"Apify run for {actor} returned nothing; check the run in the Apify console.")
    dataset_id = run_field(run, "defaultDatasetId", "default_dataset_id")
    if not dataset_id:
        raise RuntimeError(f"Apify run for {actor} gave no dataset id; check the run in the Apify console.")
    usage = run_field(run, "usageTotalUsd", "usage_total_usd")
    try:
        usage = float(usage) if usage is not None else None
    except (TypeError, ValueError):
        usage = None
    profiles = [dict(i) for i in client.dataset(dataset_id).iterate_items() if isinstance(i, dict) and i.get("username")]
    return profiles, {"items": len(profiles), "usage_usd": usage}


def harvest_comments(urls: list[str], cfg: dict, token: str, per_post: int = 25, run_cap_usd: float | None = None) -> tuple[list[dict], dict]:
    """Comments under specific posts (the hashtag Reel search returns none). One run for all URLs; each comment is one charge.
    Returns [{"text", "owner", "post"}], where post is whatever the actor says the comment belongs to (used to match it to a Reel)."""
    urls = [u for u in urls if u]
    if not urls:
        return [], {"items": 0, "usage_usd": None}
    actor = cfg.get("profile_actor_id") or cfg.get("actor_id", "REPLACE_ME")
    if actor == "REPLACE_ME":
        raise RuntimeError("Set actor_id in config/apify.json before a live run.")
    from apify_client import ApifyClient

    client = ApifyClient(token)
    run = _call(client.actor(actor), {"directUrls": urls, "resultsType": "comments", "resultsLimit": per_post, "addParentData": False}, run_cap_usd)
    if not run:
        raise RuntimeError(f"Apify run for {actor} returned nothing; check the run in the Apify console.")
    dataset_id = run_field(run, "defaultDatasetId", "default_dataset_id")
    if not dataset_id:
        raise RuntimeError(f"Apify run for {actor} gave no dataset id; check the run in the Apify console.")
    usage = run_field(run, "usageTotalUsd", "usage_total_usd")
    try:
        usage = float(usage) if usage is not None else None
    except (TypeError, ValueError):
        usage = None
    out = []
    for item in client.dataset(dataset_id).iterate_items():
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        owner = item.get("ownerUsername") or (item.get("owner") or {}).get("username") if isinstance(item.get("owner"), dict) else item.get("ownerUsername")
        post = str(item.get("postUrl") or item.get("inputUrl") or item.get("parentUrl") or item.get("url") or "")
        out.append({"text": text[:300], "owner": str(owner or "").lower(), "post": post})
    return out, {"items": len(out), "usage_usd": usage}
