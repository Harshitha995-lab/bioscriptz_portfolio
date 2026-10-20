import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

import web
from scouts import budget, research
from scouts.common import Reel, utcnow
from scouts.fake_llm import FakeLLM
from scouts.outliers import Outlier
from scouts.vault import Vault
from scouts.viral_analysis import ViralBreakdown

NOW = utcnow()


def hook(analysed=True, type="none", **kw):
    return {"analysed": analysed, "type": type if analysed else "unknown", "text": "", "description": "", "verified_quote": False, **kw}


def bd(audio="none", text="none", video="none", frames=True, aligned=None, loop="none", spice=(), beats=("hook", "point", "point", "cta"), cta="none"):
    return ViralBreakdown(reel_id="r", hooks={"audio": hook(True, audio, text="x", verified_quote=True), "text": hook(frames, text), "video": hook(frames, video)},
                          hooks_aligned=aligned, loop={"type": loop}, spice=list(spice), structure=[{"beat": b, "summary": ""} for b in beats],
                          cta={"type": cta, "text": ""})


class Decode(unittest.TestCase):
    def test_super_hook(self):
        self.assertEqual(research.super_hook(bd("bold-claim", "question", "other", True, True))["value"], "yes")
        self.assertEqual(research.super_hook(bd("bold-claim", "question", "other", True, False))["value"], "no")
        self.assertEqual(research.super_hook(bd("bold-claim", "none", "other", True, None))["value"], "no")
        self.assertEqual(research.super_hook(bd("bold-claim", frames=False))["value"], "unknown")      # unseen is never "no"

    def test_contrarian(self):
        self.assertTrue(research.contrarian_take(bd("contrarian"))["value"])
        self.assertTrue(research.contrarian_take(bd(loop="myth-bust"))["value"])
        self.assertTrue(research.contrarian_take(bd(spice=["controversy"]))["value"])
        self.assertFalse(research.contrarian_take(bd("question", loop="countdown-list"))["value"])

    def test_angle(self):
        self.assertEqual(research.content_angle(bd("contrarian")), "Contrarian / myth-bust")
        self.assertEqual(research.content_angle(bd(loop="before-after")), "Proof / before-after")
        self.assertEqual(research.content_angle(bd("number-list")), "List / how-to")
        self.assertEqual(research.content_angle(bd()), "General explainer")

    def test_rate_uses_video_length_then_transcript_then_unknown(self):
        b = bd(beats=("hook", "point", "proof", "twist", "payoff", "cta"))      # 4 reveals
        r = Reel(id="1", url="u", account="a", duration_s=20)
        self.assertEqual(research.rate_of_revelation(b, r)["per_10s"], 2.0)
        r2 = Reel(id="1", url="u", account="a", transcript=" ".join(["w"] * 52))   # 52 words / 2.6 = 20 s
        out = research.rate_of_revelation(b, r2)
        self.assertEqual(out["per_10s"], 2.0)
        self.assertIn("transcript", out["basis"])
        self.assertIsNone(research.rate_of_revelation(b, Reel(id="1", url="u", account="a"))["per_10s"])

    def test_error_breakdown_gives_error_card(self):
        o = Outlier(Reel(id="1", url="u", account="a", plays=10), 5.0, "own usual", 2.0, 1.0)
        card = research.decode(o, ViralBreakdown(reel_id="1", error="boom"))
        self.assertEqual(card["error"], "boom")


class Topic(unittest.TestCase):
    def test_clean_topic(self):
        self.assertEqual(research.clean_topic("  daily   cosmetics "), "daily cosmetics")
        for bad in ("", "   ", "x" * 61):
            with self.assertRaises(ValueError):
                research.clean_topic(bad)

    def test_keywords_include_hashtag_and_llm_failure_falls_back(self):
        kws = research.default_keywords("Daily Cosmetics")
        self.assertEqual(kws[0], "#dailycosmetics")

        class Boom:
            def complete_json(self, *a, **k):
                raise RuntimeError("down")
        self.assertEqual(research.expand_keywords("x y", Boom()), research.default_keywords("x y"))

    def test_plan_fits_free_credit(self):
        kws = research.default_keywords("skincare")
        p = research.plan_run(kws, 0.0, 2.7, 1.5)
        self.assertTrue(p.ok)
        self.assertLessEqual(p.est_cost, 1.5 + 1e-6)
        self.assertGreater(p.baseline_creators, 0)
        self.assertFalse(research.plan_run(kws, 4.9, 2.7, 1.5).ok)         # month nearly spent

    def test_baseline_creators_by_reach(self):
        reels = [Reel(id="1", url="u", account="small", plays=50000, followers=1000), Reel(id="2", url="u", account="big", plays=60000, followers=900000)]
        self.assertEqual(research.pick_baseline_creators(reels, 1), ["small"])


class Harvest(unittest.TestCase):
    def test_two_stages_baseline_not_tagged_and_spend_recorded(self):
        v = Vault(":memory:")
        calls = []

        def fake(keywords, cfg, token, max_reels, creators, **kw):
            calls.append((list(keywords), list(creators)))
            if keywords:
                return [Reel(id="k1", url="u", account="acc", plays=9000, followers=2000, keyword="x", posted_at=NOW)], {"usage_usd": 0.2}
            return [Reel(id=f"b{i}", url="u", account="acc", plays=1000, posted_at=NOW) for i in range(6)], {"usage_usd": None}

        plan = research.plan_run(research.default_keywords("skin"), 0.0, 2.7, 1.5)
        res = research.harvest_topic(v, "skin", plan, {}, "t", fake, now=NOW)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], [])                  # stage 1 searches keywords only
        self.assertEqual(calls[1][0], ["acc"][:0])         # stage 2 fetches creators only
        self.assertEqual(calls[1][1], ["acc"])
        self.assertEqual(v.get_reel("k1").niche, "skin")
        self.assertEqual(v.get_reel("b0").niche, "")       # baseline Reels are never outlier candidates
        self.assertAlmostEqual(v.month_spend(NOW), 0.2 + 6 / 1000 * 2.7)
        self.assertEqual(res["keyword_reels"], 1)

    def test_blocked_profile_scrape_keeps_stage_one(self):
        v = Vault(":memory:")

        def fake(keywords, cfg, token, max_reels, creators, **kw):
            if creators:
                raise RuntimeError("blocked")
            return [Reel(id="k1", url="u", account="acc", plays=9000, followers=2000, keyword="x", posted_at=NOW)], {"usage_usd": 0.2}
        msgs = []
        plan = research.plan_run(research.default_keywords("skin"), 0.0, 2.7, 1.5)
        res = research.harvest_topic(v, "skin", plan, {}, "t", fake, msgs.append, now=NOW)
        self.assertEqual((res["keyword_reels"], res["baseline_reels"]), (1, 0))
        self.assertEqual(v.get_reel("k1").niche, "skin")
        self.assertTrue(any("baseline" in m.lower() for m in msgs))

    def test_refuses_when_plan_not_ok(self):
        plan = research.plan_run(research.default_keywords("skin"), 4.9, 2.7, 1.5)
        with self.assertRaises(RuntimeError):
            research.harvest_topic(Vault(":memory:"), "skin", plan, {}, "t", lambda *a, **k: ([], {}), now=NOW)

    def test_decode_top_only_topic_reels_in_window(self):
        v = Vault(":memory:")
        reels = [Reel(id=f"b{i}", url="https://www.instagram.com/r/b", account="a", plays=1000, posted_at=NOW - timedelta(days=3), niche="") for i in range(6)]
        reels += [Reel(id="hit", url="https://www.instagram.com/r/h", account="a", plays=90000, posted_at=NOW - timedelta(days=2), niche="skin",
                       transcript="Stop doing this. Do that instead. Comment GLOW.")]
        reels += [Reel(id="old", url="https://www.instagram.com/r/o", account="a", plays=95000, posted_at=NOW - timedelta(days=40), niche="skin")]
        reels += [Reel(id="other", url="https://www.instagram.com/r/x", account="a", plays=99000, posted_at=NOW - timedelta(days=1), niche="hair")]
        v.upsert_reels(reels, NOW)
        from scouts.viral_analysis import load_vocab
        out = research.decode_top(v, "skin", FakeLLM(), load_vocab(), days=7, now=NOW)
        self.assertEqual([c["reel_id"] for c in out["cards"]], ["hit"])


class Web(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def serve(self, app):
        srv = web.serve(app, 0)
        self.port = srv.server_address[1]
        app_port = self.port
        srv.RequestHandlerClass = web.make_handler(app, app_port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

    def call(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait(self, jid):
        import time
        for _ in range(100):
            code, j = self.call("/api/job/" + jid)
            if j["status"] != "running":
                return j
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_sample_flow_and_script(self):
        self.serve(web.App(self.dir / "v.db", True, now=NOW))
        code, j = self.call("/api/research", {"topic": "daily cosmetics", "days": 30})
        self.assertEqual(code, 202)
        done = self.wait(j["job"])
        self.assertEqual((done["status"], done["error"]), ("done", ""))
        self.assertTrue(done["result"]["cards"])
        self.assertEqual(self.call("/api/result?topic=daily+cosmetics")[0], 200)
        code, st = self.call("/api/state")
        self.assertEqual(st["topics"][0]["topic"], "daily cosmetics")
        rid = done["result"]["cards"][0]["reel_id"]
        code, s = self.call("/api/script", {"topic": "daily cosmetics", "reel_id": rid, "my_topic": "my 3 step routine"})
        self.assertEqual(code, 200)
        self.assertIn("my 3 step routine", s["markdown"])

    def test_rejects_bad_input_and_foreign_hosts(self):
        self.serve(web.App(self.dir / "v.db", True, now=NOW))
        self.assertEqual(self.call("/api/research", {"topic": "", "days": 7})[0], 400)
        self.assertEqual(self.call("/api/research", {"topic": "x", "days": 99})[0], 400)
        self.assertEqual(self.call("/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("/api/plan", {"topic": "x"}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("/api/plan", {"topic": "x"}, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("/api/nothing")[0], 404)

    def test_only_one_run_at_a_time(self):
        app = web.App(self.dir / "v.db", True, now=NOW)
        self.serve(app)
        app.lock.acquire()
        self.addCleanup(app.lock.release)
        self.assertEqual(self.call("/api/research", {"topic": "x", "days": 7})[0], 409)

    def live_app(self, fake):
        class Live(web.App):
            def apify_cfg(self):
                return {"actor_id": "a", "price_per_1000_results_usd": 2.7, "input_verified": True}

        import os
        os.environ["APIFY_TOKEN"] = "t"
        self.addCleanup(os.environ.pop, "APIFY_TOKEN", None)
        return Live(self.dir / "v.db", False, harvester=fake, llm=FakeLLM(), now=NOW)

    def test_live_requires_confirmation_and_stays_in_budget(self):
        def fake(keywords, cfg, token, max_reels, creators, **kw):
            if keywords:
                return [Reel(id="k1", url="https://www.instagram.com/r/k", account="acc", plays=9000, followers=2000, keyword="x", posted_at=NOW)], {"usage_usd": 0.2}
            return [Reel(id=f"b{i}", url="https://www.instagram.com/r/b", account="acc", plays=1000, posted_at=NOW) for i in range(6)], {"usage_usd": 0.02}
        self.serve(self.live_app(fake))
        code, plan = self.call("/api/plan", {"topic": "skin"})
        self.assertTrue(plan["ok"])
        self.assertLessEqual(plan["est_cost"], 1.5 + 1e-6)
        self.assertEqual(self.call("/api/research", {"topic": "skin", "days": 7})[0], 400)          # no confirm, no spend
        code, j = self.call("/api/research", {"topic": "skin", "days": 7, "confirm": True})
        done = self.wait(j["job"])
        self.assertEqual((done["status"], done["error"]), ("done", ""))
        with Vault(self.dir / "v.db") as v:
            self.assertAlmostEqual(v.month_spend(NOW), 0.22)

    def test_live_blocked_until_price_set(self):
        app = web.App(self.dir / "v.db", False, llm=FakeLLM(), now=NOW)       # real apify.json: actor not set
        self.serve(app)
        code, plan = self.call("/api/plan", {"topic": "skin"})
        self.assertFalse(plan["ok"])
        self.assertEqual(self.call("/api/research", {"topic": "skin", "days": 7, "confirm": True})[0], 400)


if __name__ == "__main__":
    unittest.main()


class Compare(unittest.TestCase):
    def test_reports_disagreement(self):
        from scouts.viral_analysis import load_vocab

        class Fixed:
            def __init__(self, loop):
                self.loop = loop

            def complete_json(self, system, user, images=None):
                return {"hooks": {"audio": {"text": "Stop this", "type": "contrarian"}}, "loop": {"type": self.loop},
                        "structure": [{"beat": "hook", "summary": ""}], "cta": {"type": "none"}}

        reels = [Reel(id=str(i), url=f"u{i}", account="a", transcript="Stop this. Then more words here.") for i in range(3)]
        res = research.compare_models(reels, Fixed("myth-bust"), Fixed("curiosity-gap"), load_vocab())
        self.assertEqual(res["fields"]["story loop"], {"agree": 0, "of": 3})
        self.assertEqual(res["fields"]["spoken hook type"], {"agree": 3, "of": 3})
        self.assertEqual(len(res["differences"]), 3)       # only the loop differs; the contrarian hook fixes the angle
