import unittest
from datetime import datetime, timedelta, timezone

from scouts.common import Reel, parse_datetime, percentile_ranks, read_lines
from scouts.triage import TriageConfig, dedupe, derive_metrics, triage

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def reel(i, plays=50000, days=3, followers=10000, caption="founder brand", **kw):
    return Reel(id=str(i), url=f"u{i}", account=f"a{i}", caption=caption, plays=plays, likes=1000,
                comments=50, followers=followers, posted_at=NOW - timedelta(days=days), **kw)


class PercentileTests(unittest.TestCase):
    def test_empty_and_single(self):
        self.assertEqual(percentile_ranks([]), [])
        self.assertEqual(percentile_ranks([7]), [50.0])

    def test_order_and_range(self):
        self.assertEqual(percentile_ranks([10, 30, 20]), [0.0, 100.0, 50.0])

    def test_ties_share_average_rank(self):
        self.assertEqual(percentile_ranks([5, 5, 9]), [25.0, 25.0, 100.0])


class ParseTests(unittest.TestCase):
    def test_datetime_inputs(self):
        self.assertEqual(parse_datetime("2026-10-17T12:00:00Z"), NOW)
        self.assertEqual(parse_datetime(NOW.timestamp()), NOW)            # seconds
        self.assertEqual(parse_datetime(NOW.timestamp() * 1000), NOW)     # milliseconds
        self.assertIsNone(parse_datetime("not a date"))
        self.assertIsNone(parse_datetime(None))

    def test_read_lines_keeps_hashtags_drops_comments(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "k.txt"
            p.write_text("// note\n# heading\n#personalbranding\n\nfounder brand\n")
            self.assertEqual(read_lines(p), ["#personalbranding", "founder brand"])


class TriageTests(unittest.TestCase):
    cfg = TriageConfig(max_age_days=14, min_plays=5000, keep_top=10,
                       spam_terms=["giveaway"], relevance_terms=["brand"])

    def test_metrics(self):
        r = reel(1, plays=60000, days=3, followers=20000)
        derive_metrics(r, NOW)
        self.assertAlmostEqual(r.velocity, 20000)
        self.assertAlmostEqual(r.reach_ratio, 3.0)
        self.assertAlmostEqual(r.outperformance, 3.0)  # no median known -> falls back to reach
        self.assertAlmostEqual(r.comment_ratio, 0.05)

    def test_known_median_used_for_outperformance(self):
        r = reel(1, plays=60000, account_median_plays=10000)
        derive_metrics(r, NOW)
        self.assertAlmostEqual(r.outperformance, 6.0)

    def test_tiny_follower_count_is_floored(self):
        r = reel(1, plays=5000, followers=10)
        derive_metrics(r, NOW)
        self.assertAlmostEqual(r.reach_ratio, 5.0)  # divided by 1000, not 10

    def test_brand_new_post_is_age_floored(self):
        r = reel(1, plays=1000)
        r.posted_at = NOW
        derive_metrics(r, NOW)
        self.assertAlmostEqual(r.velocity, 4000)    # 1000 / 0.25 days

    def test_dedupe_keeps_highest_plays(self):
        out = dedupe([reel(1, plays=100), reel(1, plays=900), reel(2, plays=5)])
        self.assertEqual(sorted((r.id, r.plays) for r in out), [("1", 900), ("2", 5)])

    def test_each_filter(self):
        reels = [
            reel(1),                                   # good
            reel(1, plays=10),                         # duplicate id, fewer plays
            reel(2, days=40),                          # too old
            reel(3, plays=100),                        # too few plays
            reel(4, caption="brand giveaway time"),    # spam
            reel(5, caption="gym routine"),            # not relevant
        ]
        kept, stats = triage(reels, self.cfg, NOW)
        self.assertEqual([r.id for r in kept], ["1"])
        self.assertEqual(stats["input"], 6)
        self.assertEqual(stats["after_dedupe"], 5)
        self.assertEqual(stats["after_window"], 4)
        self.assertEqual(stats["after_min_plays"], 3)
        self.assertEqual(stats["after_spam"], 2)
        self.assertEqual(stats["kept"], 1)

    def test_keep_top_orders_by_heat(self):
        reels = [reel(i, plays=10000 * (i + 1)) for i in range(6)]
        kept, _ = triage(reels, TriageConfig(keep_top=3, relevance_terms=[]), NOW)
        self.assertEqual([r.id for r in kept][0], "5")
        self.assertEqual(len(kept), 3)
        self.assertEqual([r.heat for r in kept], sorted((r.heat for r in kept), reverse=True))

    def test_unknown_post_date_is_kept(self):
        r = reel(1)
        r.posted_at = None
        kept, _ = triage([r], self.cfg, NOW)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
