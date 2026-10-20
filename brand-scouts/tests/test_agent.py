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
