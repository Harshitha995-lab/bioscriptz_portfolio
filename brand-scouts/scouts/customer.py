"""Voice of the customer from what Instagram audiences wrote under Reels, and who gets mentioned next to a brand.

Honest limits: comments come from the few the scraper returns per Reel, skew towards people who feel strongly, and include replies
from the brand or creator themselves. This is a rough read of audience talk, not a market study. Counting is done in code;
the model only sorts each comment into one fixed theme, and every example shown is a verbatim stored comment.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from .common import Reel
from .llm import LLM

THEMES = ("question", "complaint", "praise", "price", "comparison", "purchase-intent", "other")
SYSTEM = ("[TASK:voc] You sort Instagram comments about a brand or topic. For each numbered comment choose exactly one theme from: "
          + ", ".join(THEMES) + ". question = asks something; complaint = a problem or disappointment; praise = liked it; price = about cost or value; "
          "comparison = compares with another brand or product; purchase-intent = wants to buy or asks where to get it; other = anything else. "
          'Reply as JSON: {"labels": [{"i": <number>, "theme": "<theme>"}]}. Judge only the comment text.')
BATCH = 50
MAX_COMMENTS = 400
MIN_WORDS = 3          # shorter comments (emoji, "wow", "🔥") are reactions, counted but not sorted


def collect(reels: list[Reel]) -> list[tuple[str, str]]:
    """(reel id, comment) pairs, duplicates removed, newest-first reels not preferred: plain order, capped."""
    seen, out = set(), []
    for r in reels:
        for c in (r.extras or {}).get("comments", []):
            key = re.sub(r"\s+", " ", c.lower()).strip()
            if key and key not in seen:
                seen.add(key)
                out.append((r.id, c))
    return out[:MAX_COMMENTS]


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def voice_of_customer(llm: LLM, pairs: list[tuple[str, str]]) -> dict:
    sortable = [(rid, c) for rid, c in pairs if _words(c) >= MIN_WORDS]
    reactions = len(pairs) - len(sortable)
    labels: dict[int, str] = {}
    errors = []
    for start in range(0, len(sortable), BATCH):
        chunk = sortable[start:start + BATCH]
        try:
            resp = llm.complete_json(SYSTEM, json.dumps({"comments": [{"i": start + k, "text": c[:300]} for k, (_, c) in enumerate(chunk)]}))
            for x in resp.get("labels", []):
                if isinstance(x, dict) and isinstance(x.get("i"), int) and x.get("theme") in THEMES and start <= x["i"] < start + len(chunk):
                    labels[x["i"]] = x["theme"]
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    counts = Counter(labels.values())
    themes = []
    for t in THEMES:
        idx = [i for i, th in labels.items() if th == t]
        # examples: the longest few, because they say the most; always a verbatim stored comment
        best = sorted(idx, key=lambda i: -len(sortable[i][1]))[:3]
        themes.append({"theme": t, "count": counts.get(t, 0), "share": round(counts.get(t, 0) / len(labels), 3) if labels else 0.0,
                       "examples": [{"text": sortable[i][1], "reel_id": sortable[i][0]} for i in best]})
    themes.sort(key=lambda x: -x["count"])
    return {"comments": len(pairs), "sorted": len(labels), "reactions": reactions, "themes": themes, "errors": errors[:3],
            "caveat": "A rough read of the comments the scraper returned (a few per Reel). They skew towards people with strong feelings and "
                      "include the creator's own replies. Not a market study."}


def mention_signals(reels: list[Reel], ignore: set[str] | None = None, top: int = 10) -> dict:
    """Accounts tagged or mentioned, and hashtags used, across Reels: counted per Reel (once each), skipping the Reel's own creator."""
    ignore = {x.lower().lstrip("@#") for x in (ignore or set())}
    accounts: Counter = Counter()
    tags: Counter = Counter()
    for r in reels:
        ex = r.extras or {}
        for a in set(ex.get("mentions", []) + ex.get("tagged", [])):
            if a != r.account.lower() and a not in ignore:
                accounts[a] += 1
        for h in set(ex.get("hashtags", [])):
            if h not in ignore:
                tags[h] += 1
    return {"accounts": accounts.most_common(top), "hashtags": tags.most_common(top), "reels": len(reels)}
