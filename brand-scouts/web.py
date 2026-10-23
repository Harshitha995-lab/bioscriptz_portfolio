#!/usr/bin/env python3
"""Local web app: type a topic, get the top outlier Reels of the last N days, decoded.

    python3 web.py --sample        # offline demo, synthetic data, no keys, no spend
    python3 web.py                 # live: needs APIFY_TOKEN, a Claude or Gemini key (LLM_PROVIDER in .env) and config/apify.json

Runs on 127.0.0.1 only. A live run spends Apify credit, so it shows the estimated cost first and needs a click to confirm.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scouts import research, workbook
from scouts.common import ROOT, Reel, load_env, load_json, utcnow
from scouts.vault import Vault

STATIC = Path(__file__).parent / "static"
LINK_OK = re.compile(r"^https://(www\.)?instagram\.com/")
MAX_BODY = 20_000


def slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60] or "topic"


CREATOR_MIN_PLAYS = 10_000     # in Creators mode an outlier must also be a big Reel in absolute terms, not a 1,200-play spike


class App:
    def __init__(self, vault_path: Path, sample: bool, harvester=None, llm=None, now=None, max_run_usd: float = 1.5, discoverer=None, detailer=None):
        self.vault_path, self.sample, self.harvester, self.llm, self.now = vault_path, sample, harvester, llm, now
        self.discoverer, self.detailer = discoverer, detailer
        self.fetcher = None            # stand-in for workbook.fetch_text in tests
        self.commenter = None          # stand-in for instagram_harvest.harvest_comments in tests
        self.max_run_usd = max_run_usd
        self.settings = load_json(ROOT / "config" / "settings.json")
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()          # one research run at a time, so two clicks cannot spend twice
        self.running: str | None = None

    # -- helpers
    def vault(self) -> Vault:
        return Vault(self.vault_path)

    def apify_cfg(self) -> dict:
        return load_json(ROOT / "config" / "apify.json")

    def get_llm(self, task: str):
        if self.llm is not None:
            return self.llm
        if self.sample:
            from scouts.fake_llm import FakeLLM
            return FakeLLM()
        from scouts.llm import make_llm
        return make_llm(task, self.settings)

    def live_ready(self) -> str:
        """'' when a live run can start, else the thing the user must fix."""
        if self.sample:
            return ""
        from scouts.llm import key_name
        try:
            keys = ("APIFY_TOKEN", key_name())
        except ValueError as exc:
            return str(exc)
        for k in keys:
            if not os.environ.get(k) and self.llm is None:
                return f"{k} is missing from .env"
        cfg = self.apify_cfg()
        if cfg.get("actor_id", "REPLACE_ME") == "REPLACE_ME":
            return "actor_id is not set in config/apify.json"
        if not cfg.get("input_verified"):
            return "config/apify.json input templates are not verified against the actor yet (set input_verified to true after a tiny test run)"
        if cfg.get("price_per_1000_results_usd") is None:
            return "price_per_1000_results_usd is not set in config/apify.json (copy it from the actor's Pricing tab)"
        return ""

    @staticmethod
    def resolve(topic: str, brand_raw, creators: bool = False) -> tuple[str, dict | None, list[str]]:
        """(topic key, brand details or None, search terms). In Brand mode the topic key is 'brand category'."""
        if brand_raw:
            brand = research.clean_brand(brand_raw)
            return research.clean_topic(f"{brand['brand']} {brand['category']}"), brand, research.brand_keywords(brand["brand"], brand["category"])
        topic = research.clean_topic(topic)
        if creators:
            return f"{topic} (creators)", None, research.creator_queries(topic)
        return topic, None, research.default_keywords(topic)

    def plan(self, topic: str, brand_raw=None, creators: bool = False, seeds=None, extra_n: int = 0) -> dict:
        topic, brand, kws = self.resolve(topic, brand_raw, creators)
        with self.vault() as v:
            spent = v.month_spend(self.now)
        if self.sample:
            return {"sample": True, "topic": topic, "keywords": kws, "brand": brand, "est_cost": 0.0, "ok": True, "month_spent": spent,
                    "message": "Sample mode: synthetic data, nothing is spent."}
        blocked = self.live_ready()
        cached = self.cached(topic)
        if creators and not brand:
            p = research.plan_creators(topic[:-len(" (creators)")], spent, self.apify_cfg().get("price_per_1000_results_usd"), self.max_run_usd,
                                        len(research.clean_handles(seeds))).to_dict()
            if blocked:
                p.update(ok=False, message=blocked)
            return {**p, "sample": False, "topic": topic, "cached": cached, "creators": True}
        p = research.plan_run(kws, spent, self.apify_cfg().get("price_per_1000_results_usd"), self.max_run_usd,
                              len(([brand["own"]] if brand and brand["own"] else []) + (brand["competitors"] if brand else [])) + extra_n).to_dict()
        if blocked:
            p.update(ok=False, message=blocked)
        return {**p, "sample": False, "topic": topic, "cached": cached}

    def cached(self, topic: str) -> dict | None:
        """Reels already saved for this topic by an earlier search (kept 7 days), so a failed decode need not pay Apify again."""
        with self.vault() as v:
            at = v.get_meta("harvested:" + slug(topic))
            n = len(v.reels(topic)) if at else 0
        if not at or not n:
            return None
        age = ((self.now or utcnow()) - __import__("scouts.common", fromlist=["parse_datetime"]).parse_datetime(at)).total_seconds() / 3600
        return {"reels": n, "at": at, "hours_ago": round(age, 1)} if age <= 24 * 7 else None

    # -- state
    def state(self) -> dict:
        with self.vault() as v:
            from scouts.llm import provider
            try:
                ai = provider()
            except ValueError:
                ai = "invalid"
            return {"sample": self.sample, "ai": ai, "month_spent": round(v.month_spend(self.now), 2), "free_credit": 5.0,
                    "topics": v.get_meta("topics", []), "workbooks": v.get_meta("workbooks", []),
                    "seeds": {t["topic"].lower(): v.get_meta("seeds:" + slug(t["topic"]), []) for t in v.get_meta("topics", []) if t["topic"].endswith("(creators)")},
                    "setup_issue": self.live_ready()}

    def saved(self, topic: str) -> dict | None:
        with self.vault() as v:
            return v.get_meta("research:" + slug(topic))

    # -- jobs
    def start(self, topic: str, days: int, confirm: bool, brand_raw=None, reuse: bool = False, creators: bool = False, seeds=None) -> str:
        topic, brand, _ = self.resolve(topic, brand_raw, creators)
        creators = creators and not brand
        seeds = research.clean_handles(seeds) if creators else []
        if days not in (7, 14, 30):
            raise ValueError("Pick 7, 14 or 30 days.")
        if creators and not brand_raw:
            days = 90           # a profile only returns its latest dozen posts, which span weeks: a 7-day window would hide nearly all of them
        if reuse and not self.sample and not self.cached(topic):
            raise ValueError("There are no saved Reels for this topic (or they are over a week old). Run a new search.")
        if not self.sample and not confirm and not reuse:
            raise ValueError("Confirm the estimated cost first.")
        if not self.sample and self.live_ready():
            raise ValueError(self.live_ready())
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A research run is already in progress. Wait for it to finish.")
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "status": "running", "messages": [], "result": None, "error": ""}
        self.jobs[job_id] = job
        self.running = job_id
        threading.Thread(target=self._run, args=(job, topic, days, brand, reuse, creators, seeds), daemon=True).start()
        return job_id

    def _research(self, say, topic: str, days: int, brand: dict | None = None, reuse: bool = False, creators: bool = False, seeds=None, watch=None, comments: bool = False) -> dict:
        """The research pipeline shared by the classic page and the workbook. Returns the decoded result and saves it in the vault."""
        now = self.now or utcnow()
        vocab = __import__("scouts.viral_analysis", fromlist=["load_vocab"]).load_vocab()
        with self.vault() as v:
            frames = transcriber = None
            warn = ""
            if self.sample:
                from agent import load_sample_reels
                from scouts.niches import Niches
                reels = load_sample_reels(Niches(), now)
                for r in reels:
                    r.niche = topic
                if brand:
                    research.add_sample_audience(reels)
                v.upsert_reels(reels, now)
                say("Sample mode: loaded synthetic Reels (they are about personal branding, whatever topic you typed).")
            elif reuse:
                say("Using the Reels saved earlier. " + ("Only the comments are fetched from Apify." if comments else "Apify is not called and nothing is charged by Apify."))
                if comments:
                    from scouts.instagram_harvest import harvest_comments
                    cres = research.fetch_comments(v, topic, self.apify_cfg(), os.environ.get("APIFY_TOKEN", ""), self.commenter or harvest_comments, say, now,
                                                   self.apify_cfg().get("price_per_1000_results_usd"))
                    say(f"Collected {cres['comments']} comments. Cost about ${cres['cost']:.2f}.")
                frames, transcriber, warn = research.live_media() if self.harvester is None else (None, None, "")
                if warn:
                    say(warn)
            elif creators:
                plan = research.plan_creators(topic[:-len(" (creators)")], v.month_spend(now), self.apify_cfg().get("price_per_1000_results_usd"), self.max_run_usd,
                                              len(seeds or []))
                discoverer, harvester, detailer = self.discoverer, self.harvester, self.detailer
                if discoverer is None:                  # a real run; with a stand-in discoverer (tests) the other stages only run if stand-ins are given too
                    from scouts import instagram_harvest as ih
                    discoverer, harvester, detailer = ih.harvest_creators, harvester or ih.harvest, detailer or ih.harvest_profile_details
                res = research.discover_creators(v, topic, plan, self.apify_cfg(), os.environ.get("APIFY_TOKEN", ""), discoverer, say, now,
                                                 harvester=harvester, detailer=detailer, seeds=seeds)
                v.set_meta("harvested:" + slug(topic), now.isoformat())
                say(f"Found {res['creators']} creators with {res['reels']} recent Reels ({res['seeds']} you named, {res['from_hashtags']} from top hashtag Reels, "
                    f"{res['from_search']} from name search). Cost about ${res['cost']:.2f}.")
                frames, transcriber, warn = research.live_media() if self.discoverer is None else (None, None, "")
                if warn:
                    say(warn)
            else:
                keywords = research.brand_keywords(brand["brand"], brand["category"]) if brand else research.expand_keywords(topic, self.get_llm("analysis"))
                extra = ([brand["own"]] if brand and brand["own"] else []) + (brand["competitors"] if brand else []) + list(watch or [])
                plan = research.plan_run(keywords, v.month_spend(now), self.apify_cfg().get("price_per_1000_results_usd"), self.max_run_usd, len(extra))
                harvester = self.harvester
                if harvester is None:
                    from scouts.instagram_harvest import harvest as harvester
                res = research.harvest_topic(v, topic, plan, self.apify_cfg(), os.environ.get("APIFY_TOKEN", ""), harvester, say, now,
                                          priority_creators=extra)
                v.set_meta("harvested:" + slug(topic), now.isoformat())
                say(f"Fetched {res['keyword_reels']} Reels and {res['baseline_reels']} baseline Reels. Cost about ${res['cost']:.2f}.")
                if comments:
                    from scouts.instagram_harvest import harvest_comments
                    cres = research.fetch_comments(v, topic, self.apify_cfg(), os.environ.get("APIFY_TOKEN", ""), self.commenter or harvest_comments, say, now,
                                                   self.apify_cfg().get("price_per_1000_results_usd"))
                    say(f"Collected {cres['comments']} comments. Cost about ${cres['cost']:.2f}.")
                frames, transcriber, warn = research.live_media() if self.harvester is None else (None, None, "")
                if warn:
                    say(warn)
            say("Finding outliers and decoding the top 10…")
            out = research.decode_top(v, topic, self.get_llm("analysis"), vocab, days=days, frames=frames, transcriber=transcriber,
                                      now=now, settings=self.settings["agent"], brand=brand, creators=creators, seeds=seeds, top=12 if creators else 10,
                                      min_plays=CREATOR_MIN_PLAYS if creators else 1000)
            out["sample"] = self.sample
            out["warning"] = warn
            v.set_meta("research:" + slug(topic), out)
            if creators:
                v.set_meta("seeds:" + slug(topic), seeds or [])
            topics = [t for t in v.get_meta("topics", []) if t["topic"].lower() != topic.lower()]
            v.set_meta("topics", [{"topic": topic, "at": now.isoformat(), "days": days}] + topics[:19])
        return out

    def _run(self, job: dict, topic: str, days: int, brand: dict | None = None, reuse: bool = False, creators: bool = False, seeds=None) -> None:
        try:
            job["result"] = self._research(lambda m: job["messages"].append(m), topic, days, brand, reuse, creators, seeds)
            job["status"] = "done"
        except Exception as exc:
            job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"
        finally:
            self.running = None
            self.lock.release()

    # -- workbook: type a brand, get the strategy workbook (research -> audience -> ideas -> scripts)
    @staticmethod
    def wb_params(raw: dict) -> dict:
        brand = research.clean_brand({"brand": raw.get("brand"), "category": raw.get("category"), "own": raw.get("own", ""), "competitors": []})
        days = int(raw.get("days", 30))
        if days not in (7, 14, 30, 90):
            raise ValueError("Pick 7, 14, 30 or 90 days.")
        sites = []
        for line in str(raw.get("competitor_sites") or "").splitlines()[:5]:
            line = line.strip()
            if not line:
                continue
            name, _, url = line.partition("|") if "|" in line else ("", "", line)
            url = url.strip()[:200]
            if not url:
                continue
            host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            sites.append((" ".join(name.split())[:40] or host, url))
        return {"brand": brand, "days": days, "watch": research.clean_handles(raw.get("watch")), "website": str(raw.get("website") or "").strip()[:200],
                "competitor_sites": sites}

    def wb_plan(self, raw: dict) -> dict:
        p = self.wb_params(raw)
        topic, _, _ = self.resolve("", p["brand"])
        plan = self.plan("", p["brand"], extra_n=len(p["watch"]))
        plan["topic"] = topic
        if not self.sample:
            extra = research.comments_cost(plan.get("price"))
            plan["comments_cost"] = extra
            plan["est_cost"] = round(plan["est_cost"] + extra, 4)
            plan["message"] = (plan.get("message") or "") + f" Includes about ${extra:.2f} for comments under the top Reels."
        plan["note"] = "The research step is the only one that spends Apify credit. Reading websites and the AI steps use your Gemini or Claude key."
        return plan

    def wb_start(self, raw: dict, confirm: bool, reuse: bool) -> str:
        p = self.wb_params(raw)
        topic, _, _ = self.resolve("", p["brand"])
        if reuse and not self.sample and not self.cached(topic):
            raise ValueError("There are no saved Reels for this brand (or they are over a week old). Run a new search.")
        if not self.sample and not confirm and not reuse:
            raise ValueError("Confirm the estimated cost first.")
        if not self.sample and self.live_ready():
            raise ValueError(self.live_ready())
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A run is already in progress. Wait for it to finish.")
        job = {"id": uuid.uuid4().hex[:12], "status": "running", "messages": [], "step": 0, "wb_id": "", "result": None, "error": ""}
        self.jobs[job["id"]] = job
        self.running = job["id"]
        p["comments_ok"] = bool(confirm)          # a re-use run fetches comments only when the user also confirmed the small cost
        threading.Thread(target=self._wb_a, args=(job, p, reuse), daemon=True).start()
        return job["id"]

    def _wb_sites(self, p: dict, say) -> dict:
        out = {"brand": None, "competitors": []}
        llm = self.get_llm("analysis")
        targets = ([("brand", p["brand"]["brand"], p["website"])] if p["website"] else []) + [("comp", n, u) for n, u in p["competitor_sites"]]
        for kind, name, url in targets:
            say(f"Reading {name}'s website…")
            try:
                page = ({"url": url, "title": "", "text": f"{name} sample page text. A short description of what the business sells and who it is for."}
                        if self.sample else (self.fetcher or workbook.fetch_text)(url))
                prof = workbook.site_profile(llm, page, name)
            except Exception as exc:
                prof = {"who": name, "url": url, "error": f"{type(exc).__name__}: {exc}"}
            if prof.get("error"):
                say(f"Could not use {name}'s website: {prof['error']}")
            if kind == "brand":
                out["brand"] = prof
            else:
                out["competitors"].append(prof)
        return out

    def _wb_save(self, wb: dict) -> None:
        with self.vault() as v:
            v.set_meta("wb:" + wb["id"], wb)
            rows = [r for r in v.get_meta("workbooks", []) if r["id"] != wb["id"]]
            v.set_meta("workbooks", [{"id": wb["id"], "brand": wb["brand"], "category": wb["category"], "at": wb["updated_at"], "ideas": len(wb["ideas"]),
                                      "approved": len(wb["approved"]), "scripts": len(wb["scripts"]), "sample": wb["sample"]}] + rows[:19])

    def wb(self, wb_id: str) -> dict | None:
        with self.vault() as v:
            return v.get_meta("wb:" + slug(wb_id))

    def _wb_a(self, job: dict, p: dict, reuse: bool) -> None:
        """Steps 1 to 3: research, audience, ideas. Stops at the approval gate; nothing is scripted until the user approves."""
        say = lambda m: job["messages"].append(m)
        try:
            now = self.now or utcnow()
            brand = p["brand"]
            topic, _, _ = self.resolve("", brand)
            wb_id = slug(topic)
            job["wb_id"] = wb_id
            say(f"Researching {brand['brand']} ({brand['category']})…")
            out = self._research(say, topic, p["days"], brand=brand, reuse=reuse, watch=p["watch"], comments=(not reuse) or p["comments_ok"])
            sites = self._wb_sites(p, say)
            job["step"] = 1
            llm = self.get_llm("analysis")
            with self.vault() as v:
                reels = v.reels(topic)
            from scouts.customer import collect
            pairs = collect(reels)
            say(f"Sorting {len(pairs)} real comments by how aware each writer is…")
            aw = workbook.awareness_map(llm, pairs, brand["brand"], brand["category"])
            say("Writing audience avatars from those comments…")
            av = workbook.avatars(llm, aw, brand["brand"], brand["category"])
            job["step"] = 2
            ctx = {"brand": brand["brand"], "category": brand["category"],
                   "site": {k: v for k, v in (sites.get("brand") or {}).items() if k in ("positioning", "hero_product", "price", "claims", "tone") and v}}
            say("Pairing winning formats with the audience…")
            ideas = workbook.ideation(llm, ctx, out["cards"], av)
            wb = {"id": wb_id, "brand": brand["brand"], "category": brand["category"], "topic": topic, "days": p["days"], "sample": self.sample,
                  "created_at": now.isoformat(), "updated_at": now.isoformat(), "research": out, "sites": sites, "awareness": aw, "avatars": av,
                  "ideas": ideas["ideas"], "ideas_note": self._wb_why_no_ideas(ideas, out, p["days"]), "approved": [], "scripts": [], "ctx": ctx,
                  "feed": workbook.build_feed(reels, p["watch"], [c["creator"] for c in out["cards"]]), "watch": p["watch"]}
            self._wb_save(wb)
            job["status"] = "gate"
            say("Your turn: approve the ideas you would shoot. Scripts are written only for those.")
        except Exception as exc:
            job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"
        finally:
            self.running = None
            self.lock.release()

    @staticmethod
    def _wb_why_no_ideas(ideas: dict, out: dict, days: int) -> str:
        if ideas["ideas"]:
            return ideas.get("note", "")
        st = out.get("stats") or {}
        failed = sum(1 for c in out.get("cards", []) if c.get("error"))
        bits = [f"{st.get('considered', 0)} Reels were posted in the last {days} days and {st.get('outliers', 0)} of them were outliers."]
        if failed:
            bits.append(f"{failed} outlier Reel(s) could not be decoded (see the AI error on Sheet 4).")
        if not out.get("cards"):
            bits.append("Try a longer look-back (90 days).")
        return " ".join(bits) + " " + ideas.get("note", "")

    def wb_approve(self, wb_id: str, approved) -> str:
        wb = self.wb(wb_id)
        if wb is None:
            raise ValueError("Unknown workbook.")
        if not isinstance(approved, list) or not all(isinstance(i, int) and 0 <= i < len(wb["ideas"]) for i in approved):
            raise ValueError("Approve ideas by their row number.")
        if not self.sample and self.live_ready():
            raise ValueError(self.live_ready())
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A run is already in progress. Wait for it to finish.")
        job = {"id": uuid.uuid4().hex[:12], "status": "running", "messages": [], "step": 3, "wb_id": wb["id"], "result": None, "error": ""}
        self.jobs[job["id"]] = job
        self.running = job["id"]
        threading.Thread(target=self._wb_b, args=(job, wb, sorted(set(approved))), daemon=True).start()
        return job["id"]

    def _wb_b(self, job: dict, wb: dict, approved: list[int]) -> None:
        """Steps 4 and 5: a script and storyboard for every approved idea, then the presentation pack."""
        say = lambda m: job["messages"].append(m)
        try:
            llm = self.get_llm("scripts")
            have = {s["idea"] for s in wb["scripts"]}
            cards = {c["link"]: c for c in wb["research"]["cards"] if not c.get("error")}
            own = json.dumps(wb["ctx"])
            for i in approved:
                if i in have:
                    continue
                idea = wb["ideas"][i]
                say(f"Writing the script and storyboard for idea {i + 1}…")
                sb = workbook.storyboard(llm, idea, wb["ctx"], cards.get(idea.get("source_link")), own)
                if sb.get("error"):
                    say(f"Idea {i + 1} failed: {sb['error']}")
                    continue
                wb["scripts"].append({"idea": i, "id": f"S-{len(wb['scripts']) + 1:02d}", "hook": idea["hook"], "format": idea["format"], **sb})
            wb["scripts"] = [s for s in wb["scripts"] if s["idea"] in approved]
            for n, s in enumerate(wb["scripts"]):
                s["id"] = f"S-{n + 1:02d}"
            wb["approved"] = approved
            wb["updated_at"] = (self.now or utcnow()).isoformat()
            job["step"] = 4
            self._wb_save(wb)
            job["status"] = "done"
            say("Workbook ready.")
        except Exception as exc:
            job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"
        finally:
            self.running = None
            self.lock.release()

    def wb_export(self, wb_id: str) -> bytes:
        wb = self.wb(wb_id)
        if wb is None:
            raise ValueError("Unknown workbook.")
        return workbook.to_xlsx(wb)

    def wb_vault(self) -> list[dict]:
        with self.vault() as v:
            return [{"id": r["id"], "title": r["title"], "niche": r["niche"], "status": r["status"], "created_at": r["created_at"]} for r in v.scripts()][:100]

    def script(self, topic: str, reel_id: str, my_topic: str) -> dict:
        from scouts.agent_script import write_one
        from scouts.angles import load_angles
        from scouts.report import render_script
        from scouts.viral_analysis import load_vocab
        my_topic = research.clean_topic(my_topic)
        brief = (ROOT / "config" / "brand_brief.md").read_text(encoding="utf-8")
        mp = ROOT / "config" / "my_material.md"
        cfg = self.settings["scripts"]
        with self.vault() as v:
            sid, res = write_one(v, self.get_llm("scripts"), load_vocab(), brief, mp.read_text(encoding="utf-8") if mp.exists() else "", cfg,
                                 topic=my_topic, niche=topic, from_reel_id=reel_id, angle_meanings=load_angles(ROOT / "config" / "angles.txt"))
        return {"id": sid, "markdown": render_script(res, (self.now or utcnow()).strftime("%Y-%m-%d"), self.sample, cfg)}


def make_handler(app: App, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    static = {"/": ("bioscriptz.html", "text/html; charset=utf-8"), "/bioscriptz.js": ("bioscriptz.js", "application/javascript; charset=utf-8"),
              "/bioscriptz.css": ("bioscriptz.css", "text/css; charset=utf-8"), "/classic": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "application/javascript; charset=utf-8"),
              "/style.css": ("style.css", "text/css; charset=utf-8")}

    class Handler(BaseHTTPRequestHandler):
        server_version = "OutlierResearch"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None) -> None:
            self.send_response(code)
            for k, val in (extra or {}).items():
                self.send_header(k, val)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, default=str).encode())

        def _host_ok(self) -> bool:
            # Blocks DNS-rebinding and cross-site requests: this server can spend money, so only our own page may call it.
            if self.headers.get("Host") not in hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin.split("://", 1)[-1] in hosts

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            u = urlparse(self.path)
            if u.path in static:
                name, ctype = static[u.path]
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            if u.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if u.path == "/api/wb":
                wb = app.wb((parse_qs(u.query).get("id") or [""])[0])
                return self._json(200, wb) if wb else self._json(404, {"error": "unknown workbook"})
            if u.path == "/api/wb/vault":
                return self._json(200, app.wb_vault())
            if u.path == "/api/wb/export":
                wid = (parse_qs(u.query).get("id") or [""])[0]
                try:
                    data = app.wb_export(wid)
                except ValueError as exc:
                    return self._json(404, {"error": str(exc)})
                return self._send(200, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  {"Content-Disposition": f'attachment; filename="{slug(wid)}-strategy.xlsx"'})
            if u.path == "/api/state":
                return self._json(200, app.state())
            if u.path.startswith("/api/job/"):
                job = app.jobs.get(u.path.rsplit("/", 1)[-1])
                return self._json(200, job) if job else self._json(404, {"error": "unknown job"})
            if u.path == "/api/result":
                topic = (parse_qs(u.query).get("topic") or [""])[0]
                res = app.saved(topic) if topic else None
                return self._json(200, res) if res else self._json(404, {"error": "no saved result for that topic"})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            if (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
                return self._json(415, {"error": "send JSON"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._json(413, {"error": "too large"})
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("send a JSON object")
                path = urlparse(self.path).path
                if path == "/api/plan":
                    return self._json(200, app.plan(str(body.get("topic", "")), body.get("brand"), body.get("creators") is True, body.get("seeds")))
                if path == "/api/research":
                    jid = app.start(str(body.get("topic", "")), int(body.get("days", 7)), body.get("confirm") is True, body.get("brand"), body.get("reuse") is True, body.get("creators") is True, body.get("seeds"))
                    return self._json(202, {"job": jid})
                if path == "/api/wb/plan":
                    return self._json(200, app.wb_plan(body))
                if path == "/api/wb/start":
                    return self._json(202, {"job": app.wb_start(body, body.get("confirm") is True, body.get("reuse") is True)})
                if path == "/api/wb/approve":
                    return self._json(202, {"job": app.wb_approve(str(body.get("id", "")), body.get("approved"))})
                if path == "/api/script":
                    return self._json(200, app.script(str(body.get("topic", "")), str(body.get("reel_id", "")), str(body.get("my_topic", ""))))
                self._json(404, {"error": "not found"})
            except RuntimeError as exc:
                self._json(409, {"error": str(exc)})
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc.args[0]) if exc.args else str(exc)})
            except Exception as exc:
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


class Server(ThreadingHTTPServer):
    # On Windows, address reuse lets a second copy bind a port that a first copy is still serving, and the OLD copy keeps
    # answering the browser (with its old settings). Refuse instead, so there is never a hidden second copy.
    allow_reuse_address = os.name != "nt"


def serve(app: App, port: int) -> ThreadingHTTPServer:
    return Server(("127.0.0.1", port), make_handler(app, port))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--vault")
    ap.add_argument("--max-run-usd", type=float, default=1.5, help="most one topic search may cost (default 1.50 of the 5.00 free credit)")
    args = ap.parse_args(argv)
    load_env()
    path = Path(args.vault) if args.vault else ROOT / "data" / ("sample_vault.db" if args.sample else "vault.db")
    app = App(path, args.sample, max_run_usd=args.max_run_usd)
    try:
        server = serve(app, args.port)
    except OSError:
        print(f"Port {args.port} is already in use. Another copy of this app is probably still running in another PowerShell window.\n"
              f"Close that window (or press Ctrl+C in it), then start this again. Or use a different port: web.py --port {args.port + 1}")
        return 1
    from scouts.llm import provider
    try:
        ai = provider()
    except ValueError as exc:
        print(exc)
        return 1
    print(f"Open http://127.0.0.1:{args.port}   ({'SAMPLE mode, synthetic data' if args.sample else 'LIVE mode'}, AI: {'sample stand-in' if args.sample else ai})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
