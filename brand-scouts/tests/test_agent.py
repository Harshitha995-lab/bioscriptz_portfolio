import csv
import json
import shutil
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from io import StringIO
from pathlib import Path

import agent
from scouts import budget
from scouts.common import Reel, utcnow
from scouts.export import safe_cell
from scouts.niches import Niches
from scouts.outliers import find_outliers
from scouts.vault import Vault

NOW = utcnow()


def reel(i, account="a", plays=1000, days=2, followers=None, **kw):
    return Reel(id=str(i), url=f"https://x/{i}", account=account, plays=plays, followers=followers, posted_at=NOW - timedelta(days=days), **kw)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        shutil.copy(agent.ROOT / "config" / "niches.json", self.dir / "niches.json")
        self.base = ["--vault", str(self.dir / "v.db")]
        self.apify = {"actor_id": "a", "profile_actor_id": "a", "price_per_1000_results_usd": None, "input_verified": True}
        real = agent.load_json
        patcher = mock.patch("agent.load_json", lambda path: self.apify if str(path).endswith("apify.json") else real(path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv, **kw):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = agent.main([*self.base, *argv], niches_path=self.dir / "niches.json", **kw)
        return code, out.getvalue(), err.getvalue()


class Budget(unittest.TestCase):
    def test_refuses_over_budget_and_allows_within(self):
        big = budget.make_plan(24, 0, 100, 0, 2.7)          # ~$6.48
        self.assertFalse(budget.check(big, 0.0)[0])
        small = budget.make_plan(24, 0, 50, 0, 2.7)         # ~$3.24
        self.assertTrue(budget.check(small, 0.0)[0])
        self.assertFalse(budget.check(small, 3.0)[0])       # spent already

    def test_recommend_fits(self):
        kw, cr = budget.recommend(5.0, 2.7, 24, 20)
        plan = budget.make_plan(24, 20, kw, cr, 2.7)
        self.assertLessEqual(plan.est_cost, 5.0 - budget.RESERVE_USD)
        self.assertGreaterEqual(cr, 5)

    def test_per_run_cap_sums_within_remaining(self):
        self.assertLessEqual(budget.per_run_cap(5.0, 10) * 10, 5.0 - budget.RESERVE_USD + 1e-6)


class Outliers(unittest.TestCase):
    def test_tiers(self):
        reels = [reel(i, "a", 1000) for i in range(6)] + [reel("big", "a", 61000)]
        reels += [reel("tiny", "t", 5000, followers=200)]                 # no usual: weak (vs followers)
        reels += [reel("star", "s", 900000, followers=5_000_000)]         # big account, ordinary for its size: not flagged
        outs, _ = find_outliers(reels, now=NOW)
        by = {o.reel.id: o for o in outs}
        self.assertTrue(by["big"].strong)
        self.assertFalse(by["tiny"].strong)
        self.assertNotIn("star", by)
        self.assertNotIn("0", by)

    def test_old_and_low_plays_excluded(self):
        reels = [reel(i, "a", 1000) for i in range(6)] + [reel("old", "a", 99000, days=90), reel("low", "a", 900)]
        outs, _ = find_outliers(reels, now=NOW)
        self.assertEqual(outs, [])


class VaultTests(unittest.TestCase):
    def test_upsert_keeps_enrichment_and_snapshots(self):
        v = Vault(":memory:")
        v.upsert_reels([reel("1", plays=100, niche="X", keyword="k", transcript="hello")], NOW)
        v.upsert_reels([reel("1", plays=500)], NOW + timedelta(days=1))
        r = v.get_reel("1")
        self.assertEqual((r.plays, r.niche, r.keyword, r.transcript), (500, "X", "k", "hello"))
        self.assertEqual(len(v.snapshots("1")), 2)

    def test_search_is_parameterised(self):
        v = Vault(":memory:")
        v.add_script({"title": "T", "topic": "x"})
        self.assertEqual(v.scripts(search="'; DROP TABLE scripts; --"), [])
        self.assertEqual(len(v.scripts()), 1)

    def test_bad_status_rejected(self):
        v = Vault(":memory:")
        sid = v.add_script({"title": "T"})
        with self.assertRaises(ValueError):
            v.update_script(sid, status="bogus")


class Niche(unittest.TestCase):
    def test_validation(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        n = Niches(d / "n.json")
        n.add_niche("A")
        added, skipped = n.add_creators("A", ["good_one", "bad handle!", "good_one"])
        self.assertEqual(added, 1)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(n.keyword_map(), {})
        n.add_keywords("A", ["#Foo"])
        self.assertEqual(n.keyword_map(), {"foo": "A"})


class Export(unittest.TestCase):
    def test_safe_cell(self):
        for bad in ("=1+1", "+1", "-1", "@x", "\tx"):
            self.assertTrue(safe_cell(bad).startswith("'"))
        self.assertEqual(safe_cell("fine"), "fine")


class EndToEnd(Cli):
    def test_sample_flow(self):
        self.assertEqual(self.run_cli("--sample", "harvest")[0], 0)
        code, out, _ = self.run_cli("--sample", "outliers")
        self.assertEqual(code, 0)
        self.assertIn("strong", out)
        self.assertEqual(self.run_cli("--sample", "analyse")[0], 0)
        code, out, _ = self.run_cli("--sample", "script", "--topic", "weekly posting", "--from-reel", "sample_prof_3_01")
        self.assertEqual(code, 0)
        self.assertIn("Saved to the vault as script #1", out)
        self.assertEqual(self.run_cli("vault", "status", "1", "posted")[0], 0)
        self.assertIn("posted", self.run_cli("vault", "list")[1])
        p = self.dir / "s.csv"
        self.assertEqual(self.run_cli("vault", "export", "--format", "csv", "--out", str(p))[0], 0)
        with open(p, encoding="utf-8-sig") as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), 1)

    def test_empty_vault_and_unknown_reel_are_usage_errors(self):
        self.assertEqual(self.run_cli("--sample", "outliers")[0], 2)
        self.assertEqual(self.run_cli("--sample", "script", "--topic", "t", "--from-reel", "nope")[0], 2)
        self.assertEqual(self.run_cli("vault", "show", "9")[0], 2)

    def test_delete_needs_yes(self):
        self.run_cli("--sample", "harvest")
        self.run_cli("--sample", "script", "--topic", "t")
        self.assertEqual(self.run_cli("vault", "delete", "1")[0], 2)
        self.assertEqual(self.run_cli("vault", "delete", "1", "--yes")[0], 0)

    def test_dry_run_fetches_nothing(self):
        called = []
        code, out, _ = self.run_cli("harvest", "--dry-run", harvester=lambda *a, **k: called.append(1))
        self.assertEqual((code, called), (0, []))
        self.assertIn("ASSUMED", out)

    def test_live_harvest_refuses_over_budget_and_caps_runs(self):
        import os
        os.environ["APIFY_TOKEN"] = "t"
        self.addCleanup(os.environ.pop, "APIFY_TOKEN", None)
        calls = []

        def fake(keywords, cfg, token, max_reels, creators, **kw):
            calls.append(kw)
            return [reel("n1", keyword="personalbranding", plays=5000)], {"usage_usd": 0.4, "skipped": 0}

        code, _, err = self.run_cli("harvest", "--price", "2.7", "--per-keyword", "200", harvester=fake)
        self.assertEqual((code, calls), (3, []))                       # 24 x 200 x 2.7 is far over the free credit
        code, out, _ = self.run_cli("harvest", "--price", "2.7", "--per-keyword", "10", harvester=fake)
        self.assertEqual(code, 0)
        self.assertLessEqual(calls[0]["run_cap_usd"], 5.0)
        self.assertGreater(calls[0]["run_cap_usd"], 0)
        v = Vault(self.dir / "v.db")
        self.assertAlmostEqual(v.month_spend(), 0.4)                    # Apify-reported usage, not the estimate
        self.assertEqual(v.get_reel("n1").niche, "Personal branding")   # tagged from its keyword

    def test_second_run_refused_when_month_is_spent(self):
        import os
        os.environ["APIFY_TOKEN"] = "t"
        self.addCleanup(os.environ.pop, "APIFY_TOKEN", None)
        Vault(self.dir / "v.db").record_run("harvest", 4.5, 100)
        code, *_ = self.run_cli("harvest", "--price", "2.7", "--per-keyword", "10", harvester=lambda *a, **k: ([], {}))
        self.assertEqual(code, 3)

    def test_live_refuses_until_input_verified(self):
        self.apify["input_verified"] = False
        code, _, err = self.run_cli("harvest", "--price", "2.7", "--per-keyword", "10", harvester=lambda *a, **k: ([], {}))
        self.assertEqual(code, 2)
        self.assertIn("verified", err)
        self.assertEqual(self.run_cli("harvest", "--dry-run")[0], 0)          # planning stays allowed

    def test_live_requires_price(self):
        code, _, err = self.run_cli("harvest")
        self.assertEqual(code, 2)
        self.assertIn("price", err)


if __name__ == "__main__":
    unittest.main()


class BatchTier(unittest.TestCase):
    def test_no_followers_no_usual_uses_batch_median(self):
        reels = [reel(i, f"acc{i}", 1000 + i) for i in range(12)] + [reel("hit", "zed", 50000)]
        outs, _ = find_outliers(reels, now=NOW)
        self.assertEqual([o.reel.id for o in outs], ["hit"])
        self.assertEqual(outs[0].basis, "batch")
        self.assertFalse(outs[0].strong)

    def test_too_small_a_batch_gives_no_outliers(self):
        reels = [reel(i, f"acc{i}", 1000 + i) for i in range(5)] + [reel("hit", "zed", 50000)]
        self.assertEqual(find_outliers(reels, now=NOW)[0], [])


class GeminiTests(unittest.TestCase):
    """GeminiLLM against stand-in google.genai modules: checks our glue (request shape, pacing, retries), not Google's service."""

    def install_fake(self, replies):
        import sys, types
        seen = {"calls": 0, "contents": []}

        class Part:
            @staticmethod
            def from_bytes(data, mime_type):
                return ("image", mime_type, len(data))

        class Config:
            def __init__(self_inner, **kw):
                self_inner.kw = kw
        genai = types.ModuleType("google.genai")
        types_mod = types.ModuleType("google.genai.types")
        types_mod.Part, types_mod.GenerateContentConfig = Part, Config

        class Models:
            def generate_content(self_inner, model, contents, config):
                seen["calls"] += 1
                seen["model"], seen["contents"], seen["config"] = model, contents, config.kw
                r = replies.pop(0)
                if isinstance(r, Exception):
                    raise r
                return types.SimpleNamespace(text=r)

        class Client:
            def __init__(self_inner, api_key=None):
                seen["key"] = api_key
                self_inner.models = Models()
        genai.Client, genai.types = Client, types_mod
        google = types.ModuleType("google")
        google.genai = genai
        saved = {k: sys.modules.get(k) for k in ("google", "google.genai", "google.genai.types")}
        sys.modules.update({"google": google, "google.genai": genai, "google.genai.types": types_mod})

        def restore():
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.addCleanup(restore)
        return seen

    def test_request_shape_and_json_parse(self):
        from scouts.llm import GeminiLLM
        seen = self.install_fake(['```json\n{"ok": true}\n```'])
        llm = GeminiLLM(model="m1", api_key="K", min_interval=0, sleep=lambda s: None)
        self.assertEqual(llm.complete_json("SYS", "USER", images=[b"abc"]), {"ok": True})
        self.assertEqual((seen["model"], seen["key"]), ("m1", "K"))
        self.assertEqual(seen["contents"], [("image", "image/jpeg", 3), "USER"])
        self.assertTrue(seen["config"]["system_instruction"].startswith("SYS"))
        self.assertEqual(seen["config"]["response_mime_type"], "application/json")

    def test_retries_rate_limits_then_succeeds_and_gives_up_on_other_errors(self):
        from scouts.llm import GeminiLLM
        pauses = []
        seen = self.install_fake([RuntimeError("429 RESOURCE_EXHAUSTED"), RuntimeError("503 UNAVAILABLE"), '{"ok": 1}'])
        llm = GeminiLLM(model="m", api_key="K", min_interval=0, sleep=pauses.append)
        self.assertEqual(llm.complete_json("S", "U"), {"ok": 1})
        self.assertEqual((seen["calls"], pauses), (3, [5, 20]))
        seen = self.install_fake([ValueError("400 invalid api key")])
        with self.assertRaises(ValueError):
            GeminiLLM(model="m", api_key="K", min_interval=0, sleep=lambda s: None).complete_json("S", "U")
        self.assertEqual(seen["calls"], 1)                       # a real error is not retried

    def test_gives_up_after_the_last_pause(self):
        from scouts.llm import GeminiLLM
        seen = self.install_fake([RuntimeError("429")] * 4)
        with self.assertRaises(RuntimeError):
            GeminiLLM(model="m", api_key="K", min_interval=0, sleep=lambda s: None).complete_json("S", "U")
        self.assertEqual(seen["calls"], 4)

    def test_provider_selection(self):
        import os
        from scouts import llm as L
        old = os.environ.get("LLM_PROVIDER")
        self.addCleanup(lambda: os.environ.pop("LLM_PROVIDER", None) if old is None else os.environ.__setitem__("LLM_PROVIDER", old))
        os.environ.pop("LLM_PROVIDER", None)
        self.assertEqual((L.provider(), L.key_name()), ("anthropic", "ANTHROPIC_API_KEY"))
        os.environ["LLM_PROVIDER"] = "Gemini"
        self.assertEqual((L.provider(), L.key_name()), ("gemini", "GEMINI_API_KEY"))
        os.environ["LLM_PROVIDER"] = "openai"
        with self.assertRaises(ValueError):
            L.provider()

    def test_web_app_builds_gemini_when_provider_is_gemini(self):
        import os, shutil, tempfile
        from pathlib import Path
        import web
        from scouts.llm import GeminiLLM
        self.install_fake([])
        saved = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "GEMINI_API_KEY")}

        def restore():
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.addCleanup(restore)
        os.environ.update(LLM_PROVIDER="gemini", GEMINI_API_KEY="k")
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        self.assertIsInstance(web.App(d / "v.db", False).get_llm("analysis"), GeminiLLM)
