"""The strategy workbook: research -> audience -> ideas -> scripts, built only from data we actually have.

Rules this module enforces in code, not by asking nicely:
- every quote shown as a customer's words is a verbatim stored comment (the model only picks which one, by number);
- facts taken from a website are kept only if the model's evidence quote is really in the fetched page text;
- counts and shares are computed here, never by the model;
- ideas and scripts get "proof" and number fields that say what the creator must bring, never a made-up result;
- numbers in a script that appear nowhere in the user's own inputs are flagged for the creator to check.
"""
from __future__ import annotations

import html.parser
import io
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from .llm import LLM

STAGES = ("Problem unaware", "Problem aware", "Solution aware", "Product aware", "Most aware")
STAGE_HELP = ("0 Problem unaware: sees no problem, or treats it as normal. 1 Problem aware: describes the pain or need but names no kind of fix. "
              "2 Solution aware: knows a kind of fix exists and asks how to choose or what works. 3 Product aware: names or compares specific "
              "brands or products, or asks about the price or quality of one. 4 Most aware: has used it or wants to buy now (where to buy, reorder, loyalty). "
              "-1: not about this topic at all.")
SHOT_TYPES = ("Wide shot", "Medium shot", "Close-up shot", "B-roll")
ANGLES = ("Eye level", "High angle", "Low angle", "Over the shoulder")
GOALS = ("Awareness", "Sales", "Retargeting", "Retention")
BATCH = 50
MAX_COMMENTS = 300
MIN_WORDS = 3
MIN_STAGE_COMMENTS = 3        # a stage with fewer comments than this gets no avatar: there is nothing real to base one on
COMMENT_CAVEAT = ("Built from the comments the scraper returned under Instagram Reels (a few per Reel). They skew towards people with strong "
                  "feelings and include creators' own replies. Treat the shares as a rough read, not a market study.")


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%₹$.,-]", " ", str(text).lower())).strip()


# ---------------------------------------------------------------------------- awareness map (sheet 5)
def awareness_map(llm: LLM, pairs: list[tuple[str, str]], brand: str = "", category: str = "") -> dict:
    sortable = [(rid, c) for rid, c in pairs if _words(c) >= MIN_WORDS][:MAX_COMMENTS]
    system = ("[TASK:awareness] You sort Instagram comments by how aware the writer is of a problem and its solutions, for the category "
              f"'{category}' and the brand '{brand}'. {STAGE_HELP} "
              'Reply as JSON: {"labels": [{"i": <number>, "stage": <-1 to 4>}]}. Judge only the comment text.')
    labels: dict[int, int] = {}
    errors = []
    for start in range(0, len(sortable), BATCH):
        chunk = sortable[start:start + BATCH]
        try:
            resp = llm.complete_json(system, json.dumps({"comments": [{"i": start + k, "text": c[:300]} for k, (_, c) in enumerate(chunk)]}))
            for x in resp.get("labels", []):
                if isinstance(x, dict) and isinstance(x.get("i"), int) and isinstance(x.get("stage"), int) and start <= x["i"] < start + len(chunk) \
                        and -1 <= x["stage"] <= 4:
                    labels[x["i"]] = x["stage"]
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    placed = {i: s for i, s in labels.items() if s >= 0}
    counts = Counter(placed.values())
    stages = []
    for s, name in enumerate(STAGES):
        idx = sorted((i for i, st in placed.items() if st == s), key=lambda i: -len(sortable[i][1]))
        stages.append({"stage": s, "name": name, "count": counts.get(s, 0), "share": round(counts.get(s, 0) / len(placed), 3) if placed else 0.0,
                       "examples": [{"text": sortable[i][1], "reel_id": sortable[i][0]} for i in idx[:8]]})
    return {"comments": len(pairs), "sorted": len(labels), "placed": len(placed), "off_topic": len(labels) - len(placed), "stages": stages,
            "errors": errors[:3], "caveat": COMMENT_CAVEAT}


# ---------------------------------------------------------------------------- avatars (sheet 6)
def avatars(llm: LLM, awareness: dict, brand: str, category: str) -> dict:
    """One avatar per awareness stage that has enough real comments. Words are copied from stored comments by number."""
    out, skipped = [], []
    for st in awareness.get("stages", []):
        if st["count"] < MIN_STAGE_COMMENTS:
            skipped.append(f"{st['name']}: only {st['count']} comment(s), not enough to describe a real group")
            continue
        quotes = st["examples"][:8]
        system = ("[TASK:avatar] You describe one audience segment from real Instagram comments, for the category "
                  f"'{category}' and brand '{brand}'. The segment is '{st['name']}'. Use ONLY what the comments show. Do not invent age, job, "
                  "city, income or any statistic. Reply as JSON: {\"name\": \"a short human label for the segment, 2-3 words\", "
                  "\"problem\": \"the problem they face, in one sentence, from the comments\", \"belief\": \"what they think about the product or "
                  "category, from the comments\", \"objection\": \"their main doubt, from the comments\", \"formats\": [\"up to 2 content "
                  "formats or angles that would speak to them\"], \"quote\": <number of the comment that best sums them up>}")
        try:
            r = llm.complete_json(system, json.dumps({"comments": [{"i": k, "text": q["text"][:300]} for k, q in enumerate(quotes)]}))
        except Exception as exc:
            skipped.append(f"{st['name']}: the model failed ({type(exc).__name__}: {exc})")
            continue
        qi = r.get("quote") if isinstance(r.get("quote"), int) and 0 <= r["quote"] < len(quotes) else 0
        out.append({"stage": st["stage"], "stage_name": st["name"], "share": st["share"], "count": st["count"],
                    "name": str(r.get("name") or st["name"])[:40], "problem": str(r.get("problem") or "")[:300],
                    "belief": str(r.get("belief") or "")[:300], "objection": str(r.get("objection") or "")[:300],
                    "formats": [str(f)[:80] for f in (r.get("formats") or [])][:2],
                    "words": quotes[qi]["text"], "reel_id": quotes[qi]["reel_id"], "more_words": [q["text"] for k, q in enumerate(quotes) if k != qi][:2]})
    return {"avatars": out, "skipped": skipped,
            "note": "Descriptions are written by the AI from the comments; the 'exact words' are verbatim stored comments."}


# ---------------------------------------------------------------------------- ideas (sheet 7)
def _overlap(a: str, b: str) -> float:
    A, B = set(_norm(a).split()), set(_norm(b).split())
    return len(A & B) / max(min(len(A), len(B)), 1)


def ideation(llm: LLM, brand: dict, cards: list[dict], av: dict, n: int = 6) -> dict:
    """Pair the winning structures with the audience segments. Hooks that copy a source Reel's wording are dropped."""
    refs = [c for c in cards if not c.get("error")][:8]
    if not refs:
        return {"ideas": [], "note": "No decoded outliers to build ideas from."}
    names = [a["name"] for a in av.get("avatars", [])]
    system = ("[TASK:ideation] You propose short-video ideas for a brand. Each idea reuses the STRUCTURE of one winning reference Reel (its "
              "hook type, story loop and beats) on a new angle for one audience segment. Never reuse a reference's wording, examples or subject. "
              "Never state a statistic, result, review count, testimonial or client claim: the 'proof' field says what proof the creator must "
              "bring or show, as an instruction, not as a fact. "
              f"Goal must be one of {list(GOALS)}. Reply as JSON: {{\"ideas\": [{{\"format\": \"\", \"angle\": \"\", \"hook\": \"\", "
              "\"message\": \"\", \"proof\": \"\", \"cta\": \"\", \"visual\": \"\", \"avatar\": \"a segment name from the list or empty\", "
              "\"goal\": \"\", \"source\": <number of the reference>}]}")
    user = json.dumps({"brand": brand, "n": n, "segments": [{"name": a["name"], "problem": a["problem"], "objection": a["objection"]} for a in av.get("avatars", [])],
                       "references": [{"i": i + 1, "creator_tier": c.get("tier"), "angle": c.get("content_angle"), "format": c.get("format"),
                                       "structure": c.get("structure"), "story_loop": c.get("story_loop"), "hook_type": (c.get("hook") or {}).get("text", {}).get("type")}
                                      for i, c in enumerate(refs)]})
    try:
        resp = llm.complete_json(system, user)
    except Exception as exc:
        return {"ideas": [], "note": f"The model failed: {type(exc).__name__}: {exc}"}
    ideas, dropped = [], 0
    for x in resp.get("ideas", []):
        if not isinstance(x, dict) or not x.get("hook"):
            continue
        src = x.get("source") if isinstance(x.get("source"), int) and 1 <= x["source"] <= len(refs) else None
        if src is None:
            dropped += 1
            continue
        ref = refs[src - 1]
        ref_hook = " ".join(filter(None, [((ref.get("hook") or {}).get(k) or {}).get("text", "") for k in ("audio", "text")]))
        if ref_hook and _overlap(str(x["hook"]), ref_hook) > 0.6:
            dropped += 1                      # too close to the source's own words: we copy structure, never wording
            continue
        goal = x.get("goal") if x.get("goal") in GOALS else "Awareness"
        ideas.append({"format": str(x.get("format") or "")[:80], "angle": str(x.get("angle") or "")[:80], "hook": str(x["hook"])[:200],
                      "message": str(x.get("message") or "")[:300], "proof": str(x.get("proof") or "")[:300], "cta": str(x.get("cta") or "")[:160],
                      "visual": str(x.get("visual") or "")[:300], "avatar": x.get("avatar") if x.get("avatar") in names else "", "goal": goal,
                      "source": src, "source_creator": ref.get("creator"), "source_link": ref.get("link")})
    return {"ideas": ideas[:n], "dropped": dropped, "note": "Written by the AI. You approve each idea before any script is written."}


# ---------------------------------------------------------------------------- scripts and storyboard (sheet 8)
def storyboard(llm: LLM, idea: dict, brand: dict, source: dict | None, own_text: str = "") -> dict:
    system = ("[TASK:storyboard] You write a shoot-ready script for one short video, as a shot list. Keep the structure of the reference "
              "(beats) but use new words. Use plain spoken language. Never state a statistic, result, price, review count or client story "
              "unless it is in the brand facts you were given; where one is needed write [your real number] or [your proof]. "
              f"shot_type must be one of {list(SHOT_TYPES)}; angle one of {list(ANGLES)}. 5 to 8 shots. Reply as JSON: "
              "{\"storyline\": \"\", \"tone\": \"\", \"shots\": [{\"line\": \"\", \"shot_type\": \"\", \"angle\": \"\", \"action\": \"\", "
              "\"location\": \"\", \"prop\": \"\", \"equipment\": \"\", \"cut\": \"\", \"on_screen_text\": \"\", \"sound\": \"\"}], "
              "\"needs_from_you\": [\"things the creator must supply\"]}")
    ref = ({"structure": source.get("structure"), "story_loop": source.get("story_loop"), "format": source.get("format"),
            "content_angle": source.get("content_angle")} if source else {})
    try:
        r = llm.complete_json(system, json.dumps({"brand": brand, "idea": {k: idea.get(k) for k in ("format", "angle", "hook", "message", "proof", "cta", "visual", "avatar", "goal")},
                                                  "reference_structure": ref}))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "shots": []}
    allowed = _norm(own_text + " " + json.dumps(idea))
    shots, flagged = [], []
    for k, s in enumerate(r.get("shots") or []):
        if not isinstance(s, dict):
            continue
        line = str(s.get("line") or "")[:400]
        for num in re.findall(r"\d[\d,.]*", line):
            if _norm(num) not in allowed and num not in flagged:
                flagged.append(num)
        shots.append({"seq": k + 1, "line": line, "shot_type": s.get("shot_type") if s.get("shot_type") in SHOT_TYPES else "Medium shot",
                      "angle": s.get("angle") if s.get("angle") in ANGLES else "Eye level", "action": str(s.get("action") or "")[:200],
                      "location": str(s.get("location") or "")[:80], "prop": str(s.get("prop") or "")[:80], "equipment": str(s.get("equipment") or "")[:80],
                      "cut": str(s.get("cut") or "")[:80], "on_screen_text": str(s.get("on_screen_text") or "")[:120], "sound": str(s.get("sound") or "")[:80]})
    needs = [str(x)[:160] for x in (r.get("needs_from_you") or [])][:8]
    if flagged:
        needs.append("Check these numbers in the script, they are not from your inputs: " + ", ".join(flagged[:8]))
    return {"storyline": str(r.get("storyline") or "")[:300], "tone": str(r.get("tone") or "")[:200], "shots": shots, "needs_from_you": needs,
            "flagged_numbers": flagged[:8], "error": ""}


# ---------------------------------------------------------------------------- websites (sheets 1 and 2)
MAX_PAGE = 1_500_000
TEXT_CAP = 9000


class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.title, self.desc, self._in_title = [], 0, "", "", False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description") and a.get("content") and not self.desc:
                self.desc = a["content"]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip and data.strip():
            self.parts.append(data.strip())


def public_url(raw: str) -> str:
    """http(s) only, with a hostname that resolves to public addresses. A page we fetch for the user must never reach their own network."""
    url = str(raw or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("Give a normal website address, for example https://example.com")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"Could not find the website '{p.hostname}'.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("That address points inside a private network, so it is not fetched.")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(urllib.parse.urljoin(req.full_url, newurl))        # every hop is checked, not just the first
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_text(raw_url: str, timeout: float = 10.0) -> dict:
    url = public_url(raw_url)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BioscriptzResearch/1.0)", "Accept": "text/html"})
    with opener.open(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            raise ValueError(f"The page is not HTML ({ctype or 'unknown type'}).")
        raw = resp.read(MAX_PAGE)
        charset = resp.headers.get_content_charset() or "utf-8"
    parser = _Text()
    parser.feed(raw.decode(charset, errors="replace"))
    text = " ".join([parser.title.strip(), parser.desc.strip()] + parser.parts)
    return {"url": url, "title": parser.title.strip()[:200], "text": re.sub(r"\s+", " ", text)[:TEXT_CAP]}


def site_profile(llm: LLM, page: dict, who: str) -> dict:
    """Facts about a business from its own page. A fact survives only if its evidence quote is really in the page text."""
    system = ("[TASK:site] You read the text of a company's website page and extract facts about it. Use ONLY the text. For each fact give "
              "an 'evidence' quote copied exactly from the text. Reply as JSON: {\"positioning\": {\"value\": \"\", \"evidence\": \"\"}, "
              "\"hero_product\": {\"value\": \"\", \"evidence\": \"\"}, \"price\": {\"value\": \"\", \"evidence\": \"\"}, "
              "\"claims\": [{\"value\": \"\", \"evidence\": \"\"}], \"tone\": {\"value\": \"\", \"evidence\": \"\"}}. "
              "Leave a field empty if the text does not say it. Never guess a price.")
    try:
        r = llm.complete_json(system, json.dumps({"business": who, "page_text": page["text"]}))
    except Exception as exc:
        return {"who": who, "url": page.get("url", ""), "error": f"{type(exc).__name__}: {exc}"}
    hay = _norm(page["text"])

    def verified(x):
        if not isinstance(x, dict) or not x.get("value"):
            return ""
        ev = _norm(x.get("evidence") or "")
        return str(x["value"])[:240] if len(ev) >= 8 and ev in hay else ""
    claims = [v for v in (verified(c) for c in (r.get("claims") or [])[:6]) if v]
    return {"who": who, "url": page["url"], "title": page.get("title", ""), "positioning": verified(r.get("positioning")),
            "hero_product": verified(r.get("hero_product")), "price": verified(r.get("price")), "claims": claims, "tone": verified(r.get("tone")),
            "error": ""}


# ---------------------------------------------------------------------------- watchlist feed (sheet 4, step 1)
def build_feed(reels: list, watch: list[str], outlier_creators: list[str], limit: int = 60) -> list[dict]:
    names = {w.lower().lstrip("@") for w in watch} | {o.lower() for o in outlier_creators}
    rows = [r for r in reels if r.account.lower() in names]
    rows.sort(key=lambda r: (r.posted_at is None, -(r.posted_at.timestamp() if r.posted_at else 0)))
    return [{"creator": r.account, "followers": r.followers, "caption": (r.caption or "")[:140], "link": r.url, "posted_at": r.posted_at.isoformat() if r.posted_at else None,
             "plays": r.plays, "likes": r.likes, "comments": r.comments} for r in rows[:limit]]


# ---------------------------------------------------------------------------- Excel export
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _cell(v):
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(FORMULA_STARTS) else s


def to_xlsx(wb: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    book = Workbook()
    book.remove(book.active)

    def sheet(name, header, rows):
        ws = book.create_sheet(name[:31])
        ws.append([_cell(h) for h in header])
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([_cell(x) for x in r])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 2, 60)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")

    sites = wb.get("sites") or {}
    comp = sites.get("competitors") or []
    sheet("1 Competitor Research", ["Competitor", "Website", "Positioning", "Hero product", "Price (as written)", "Claims on the page", "Tone", "Note"],
          [[c.get("who"), c.get("url"), c.get("positioning"), c.get("hero_product"), c.get("price"), "; ".join(c.get("claims") or []), c.get("tone"), c.get("error")] for c in comp])
    own = sites.get("brand") or {}
    sheet("2 Brand & Product", ["Brand", "Website", "Positioning", "Hero product", "Price (as written)", "Claims on the page", "Tone", "Note"],
          [[own.get("who"), own.get("url"), own.get("positioning"), own.get("hero_product"), own.get("price"), "; ".join(own.get("claims") or []), own.get("tone"), own.get("error")]] if own else [])
    aud = (wb.get("research") or {}).get("audience") or {}
    voice = (aud.get("voice") or {}).get("themes") or []
    sheet("3 Market & Customer", ["Source", "Theme", "Count", "Exact customer words (verbatim)"],
          [["Instagram comments", t["theme"], t["count"], ex["text"]] for t in voice for ex in (t["examples"] or [{"text": ""}])])
    cards = (wb.get("research") or {}).get("cards") or []
    sheet("4 Outlier Data", ["Creator", "Followers", "Plays", "Their usual plays", "Outlier score (x)", "Grade", "Content angle", "Format", "Hook (spoken)", "Hook (on-screen)", "CTA", "Structure", "Link"],
          [[c.get("creator"), c.get("followers"), c.get("plays"), c.get("usual"), c.get("ratio"), c.get("grade"), c.get("content_angle"), c.get("format"),
            ((c.get("hook") or {}).get("audio") or {}).get("text"), ((c.get("hook") or {}).get("text") or {}).get("text"),
            (c.get("cta") or {}).get("text"), " > ".join(c.get("structure") or []), c.get("link")] for c in cards if not c.get("error")])
    aw = wb.get("awareness") or {}
    sheet("5 Awareness Map", ["Stage", "Comments", "Share of sorted comments", "Example (verbatim)"],
          [[s["name"], s["count"], f"{round(s['share'] * 100)}%", (s["examples"][0]["text"] if s["examples"] else "")] for s in aw.get("stages", [])])
    sheet("6 Audience Avatars", ["Segment", "Awareness stage", "Share", "Problem", "Belief", "Objection", "Exact words (verbatim)", "Best formats"],
          [[a["name"], a["stage_name"], f"{round(a['share'] * 100)}%", a["problem"], a["belief"], a["objection"], a["words"], "; ".join(a["formats"])] for a in (wb.get("avatars") or {}).get("avatars", [])])
    ideas = wb.get("ideas") or []
    approved = set(wb.get("approved") or [])
    sheet("7 Ideation SOP", ["Format", "Angle", "Hook", "Key message", "Proof the creator must bring", "CTA", "Visual direction", "Segment", "Goal", "Source outlier", "Approved"],
          [[i.get("format"), i.get("angle"), i.get("hook"), i.get("message"), i.get("proof"), i.get("cta"), i.get("visual"), i.get("avatar"), i.get("goal"),
            i.get("source_link"), "yes" if k in approved else "no"] for k, i in enumerate(ideas)])
    rows = []
    for s in wb.get("scripts") or []:
        for sh in s.get("shots") or []:
            rows.append([s.get("id"), s.get("hook"), sh["seq"], sh["line"], sh["shot_type"], sh["angle"], sh["action"], sh["location"], sh["prop"], sh["equipment"],
                         sh["cut"], sh["on_screen_text"], sh["sound"]])
    sheet("8 Script & Storyboard", ["Script", "Hook", "Shot", "Line", "Shot type", "Angle", "Action", "Location", "Prop", "Equipment", "Cut", "On-screen text", "Sound"], rows)
    sheet("9 Presentation Pack", ["Item", "Value"],
          [["Brand", wb.get("brand")], ["Category", wb.get("category")], ["Approved ideas", len(approved)], ["Scripts", len(wb.get("scripts") or [])],
           ["Needs from you", "; ".join(n for s in (wb.get("scripts") or []) for n in s.get("needs_from_you", []))]])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()
