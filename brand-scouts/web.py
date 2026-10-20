#!/usr/bin/env python3
"""Local web app: type a topic, get the top outlier Reels of the last N days, decoded.

    python3 web.py --sample        # offline demo, synthetic data, no keys, no spend
    python3 web.py                 # live: needs APIFY_TOKEN, ANTHROPIC_API_KEY and config/apify.json

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

from scouts import research
from scouts.common import ROOT, Reel, load_env, load_json, utcnow
from scouts.vault import Vault

STATIC = Path(__file__).parent / "static"
LINK_OK = re.compile(r"^https://(www\.)?instagram\.com/")
MAX_BODY = 20_000


def slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60] or "topic"


class App:
    def __init__(self, vault_path: Path, sample: bool, harvester=None, llm=None, now=None, max_run_usd: float = 1.5):
        self.vault_path, self.sample, self.harvester, self.llm, self.now = vault_path, sample, harvester, llm, now
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
        from scouts.llm import AnthropicLLM, model_for
        return AnthropicLLM(model_for(task, self.settings))

    def live_ready(self) -> str:
        """'' when a live run can start, else the thing the user must fix."""
        if self.sample:
            return ""
        for k in ("APIFY_TOKEN", "ANTHROPIC_API_KEY"):
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
    def resolve(topic: str, brand_raw) -> tuple[str, dict | None, list[str]]:
        """(topic key, brand details or None, search terms). In Brand mode the topic key is 'brand category'."""
        if brand_raw:
            brand = research.clean_brand(brand_raw)
            return research.clean_topic(f"{brand['brand']} {brand['category']}"), brand, research.brand_keywords(brand["brand"], brand["category"])
        topic = research.clean_topic(topic)
        return topic, None, research.default_keywords(topic)

    def plan(self, topic: str, brand_raw=None) -> dict:
        topic, brand, kws = self.resolve(topic, brand_raw)
        with self.vault() as v:
            spent = v.month_spend(self.now)
        if self.sample:
            return {"sample": True, "topic": topic, "keywords": kws, "brand": brand, "est_cost": 0.0, "ok": True, "month_spent": spent,
                    "message": "Sample mode: synthetic data, nothing is spent."}
        blocked = self.live_ready()
        p = research.plan_run(kws, spent, self.apify_cfg().get("price_per_1000_results_usd"), self.max_run_usd,
                              len(([brand["own"]] if brand and brand["own"] else []) + (brand["competitors"] if brand else []))).to_dict()
        if blocked:
            p.update(ok=False, message=blocked)
        return {**p, "sample": False, "topic": topic}

    # -- state
    def state(self) -> dict:
        with self.vault() as v:
            return {"sample": self.sample, "month_spent": round(v.month_spend(self.now), 2), "free_credit": 5.0,
                    "topics": v.get_meta("topics", []), "setup_issue": self.live_ready()}

    def saved(self, topic: str) -> dict | None:
        with self.vault() as v:
            return v.get_meta("research:" + slug(topic))

    # -- jobs
    def start(self, topic: str, days: int, confirm: bool, brand_raw=None) -> str:
        topic, brand, _ = self.resolve(topic, brand_raw)
        if days not in (7, 14, 30):
            raise ValueError("Pick 7, 14 or 30 days.")
        if not self.sample and not confirm:
            raise ValueError("Confirm the estimated cost first.")
        if not self.sample and self.live_ready():
            raise ValueError(self.live_ready())
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A research run is already in progress. Wait for it to finish.")
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "status": "running", "messages": [], "result": None, "error": ""}
        self.jobs[job_id] = job
        self.running = job_id
        threading.Thread(target=self._run, args=(job, topic, days, brand), daemon=True).start()
        return job_id

    def _run(self, job: dict, topic: str, days: int, brand: dict | None = None) -> None:
        say = lambda m: job["messages"].append(m)
        try:
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
                else:
                    keywords = research.brand_keywords(brand["brand"], brand["category"]) if brand else research.expand_keywords(topic, self.get_llm("analysis"))
                    plan = research.plan_run(keywords, v.month_spend(now), self.apify_cfg().get("price_per_1000_results_usd"), self.max_run_usd,
                                             len(([brand["own"]] if brand and brand["own"] else []) + (brand["competitors"] if brand else [])))
                    harvester = self.harvester
                    if harvester is None:
                        from scouts.instagram_harvest import harvest as harvester
                    res = research.harvest_topic(v, topic, plan, self.apify_cfg(), os.environ.get("APIFY_TOKEN", ""), harvester, say, now,
                                              priority_creators=([brand["own"]] if brand and brand["own"] else []) + (brand["competitors"] if brand else []))
                    say(f"Fetched {res['keyword_reels']} Reels and {res['baseline_reels']} baseline Reels. Cost about ${res['cost']:.2f}.")
                    frames, transcriber, warn = research.live_media() if self.harvester is None else (None, None, "")
                    if warn:
                        say(warn)
                say("Finding outliers and decoding the top 10…")
                out = research.decode_top(v, topic, self.get_llm("analysis"), vocab, days=days, frames=frames, transcriber=transcriber,
                                          now=now, settings=self.settings["agent"], brand=brand)
                out["sample"] = self.sample
                out["warning"] = warn
                v.set_meta("research:" + slug(topic), out)
                topics = [t for t in v.get_meta("topics", []) if t["topic"].lower() != topic.lower()]
                v.set_meta("topics", [{"topic": topic, "at": now.isoformat(), "days": days}] + topics[:19])
                job["result"] = out
                job["status"] = "done"
        except Exception as exc:
            job["status"], job["error"] = "error", f"{type(exc).__name__}: {exc}"
        finally:
            self.running = None
            self.lock.release()

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
    static = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "application/javascript; charset=utf-8"),
              "/style.css": ("style.css", "text/css; charset=utf-8")}

    class Handler(BaseHTTPRequestHandler):
        server_version = "OutlierResearch"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
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
                    return self._json(200, app.plan(str(body.get("topic", "")), body.get("brand")))
                if path == "/api/research":
                    jid = app.start(str(body.get("topic", "")), int(body.get("days", 7)), body.get("confirm") is True, body.get("brand"))
                    return self._json(202, {"job": jid})
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


def serve(app: App, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))


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
    print(f"Open http://127.0.0.1:{args.port}   ({'SAMPLE mode, synthetic data' if args.sample else 'LIVE mode'})")
    try:
        serve(app, args.port).serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
