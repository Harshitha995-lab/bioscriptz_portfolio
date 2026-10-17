"""Step 1: pull Reels from Apify and map them into Reel objects.

The Apify actor is chosen in config/apify.json. Actors name their fields differently, so
item_to_reel() tries several common names per field (extend them with "field_map" in the
config). On a first live run, check out/<week>/raw_sample.json against the mapping.
"""
from __future__ import annotations

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
        source=source,
    )


def split_keywords(lines: list[str]) -> tuple[list[str], list[str]]:
    """Hashtags (lines starting with #, returned without it) and plain search terms."""
    hashtags = [l.lstrip("#") for l in lines if l.startswith("#")]
    terms = [l for l in lines if not l.startswith("#")]
    return hashtags, terms


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


def _run_actor(client, actor_id: str, run_input: dict, field_map, source: str, limit: int | None):
    run = client.actor(actor_id).call(run_input=run_input)
    if not run:
        raise RuntimeError(f"Apify run for {actor_id} returned nothing; check the run in the Apify console.")
    reels, raw_sample, items, skipped = [], [], 0, 0
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        items += 1
        if len(raw_sample) < 3:
            raw_sample.append(item)
        reel = item_to_reel(item, field_map, source=source)
        if reel is None:
            skipped += 1
            continue
        reels.append(reel)
        if limit and len(reels) >= limit:
            break
    return reels, {"items": items, "skipped": skipped, "raw_sample": raw_sample}


def clean_handles(lines: list[str]) -> list[str]:
    return [l.strip().lstrip("@") for l in lines if l.strip()]


def harvest(keyword_lines: list[str], cfg: dict, token: str, max_reels: int | None = None,
            creators: list[str] | None = None) -> tuple[list[Reel], dict]:
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

    if handles:
        run_input = render_template(cfg.get("profile_input_template", {}), {"{usernames}": handles})
        got, meta = _run_actor(client, cfg["profile_actor_id"], run_input, field_map, "creator", max_reels)
        reels += got
        raw_sample += meta.pop("raw_sample")
        info["creators"] = meta
        info["items"] += meta["items"]
        info["skipped"] += meta["skipped"]

    remaining = None if not max_reels else max(max_reels - len(reels), 0)
    if remaining != 0:
        hashtags, terms = split_keywords(keyword_lines)
        run_input = render_template(cfg.get("input_template", {}), {"{hashtags}": hashtags, "{terms}": terms})
        got, meta = _run_actor(client, cfg["actor_id"], run_input, field_map, "keyword", remaining)
        reels += got
        raw_sample += meta.pop("raw_sample")
        info["keywords"] = meta
        info["items"] += meta["items"]
        info["skipped"] += meta["skipped"]
    info["raw_sample"] = raw_sample
    return reels, info
