import json
import unittest
from datetime import datetime, timezone

from run_weekly import load_sample
from scouts.common import Reel
from scouts.fake_llm import FakeLLM
from scouts.llm import parse_json
from scouts.playbook import EmptyPlaybook
from scouts.scoring import DEFAULT_WEIGHTS, combine, compute_factors, momentum_score, score_brand_match, score_topics
from scouts.topics import Topic, group_topics, label_reels, normalize_topic
from scouts.triage import TriageConfig, triage

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


class ParseJsonTests(unittest.TestCase):
    def test_fenced_and_prose(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('Here you go: {"a": {"b": 2}} done'), {"a": {"b": 2}})
        with self.assertRaises(ValueError):
            parse_json("no json here")


class LabellingTests(unittest.TestCase):
    def test_cta_with_capital_c_is_detected(self):
        r = Reel(id="1", url="u", account="a", caption="Founder funnel", transcript="Comment BRAND and I will send it.")
        labelled, _ = label_reels([r], FakeLLM())
        self.assertEqual(labelled[0].cta_type, "comment-keyword")

    def test_irrelevant_and_unlabelled_are_counted_not_kept(self):
        class Partial:
            def complete_json(self, system, user):
                ids = [r["id"] for r in json.loads(user)["reels"]]
                return {"labels": [{"id": ids[0], "relevant": False}]}  # second Reel missing entirely
        rs = [Reel(id=str(i), url="u", account="a") for i in range(2)]
        labelled, stats = label_reels(rs, Partial())
        self.assertEqual((len(labelled), stats["irrelevant"], stats["unlabelled"]), (0, 1, 1))

    def test_failed_batch_is_reported_not_raised(self):
        class Broken:
            def complete_json(self, system, user):
                raise RuntimeError("api down")
        labelled, stats = label_reels([Reel(id="1", url="u", account="a")], Broken())
        self.assertEqual(labelled, [])
        self.assertIn("api down", stats["errors"][0])

    def test_invalid_angle_and_cta_fall_back(self):
        class Odd:
            def complete_json(self, system, user):
                return {"labels": [{"id": "1", "relevant": True, "topic": "  trust   matters. ", "angle": "??", "cta_type": "??"}]}
        labelled, _ = label_reels([Reel(id="1", url="u", account="a")], Odd())
        self.assertEqual((labelled[0].topic, labelled[0].angle, labelled[0].cta_type), ("Trust matters", "authority", "none"))

    def test_normalize_and_group_case_insensitive(self):
        self.assertEqual(normalize_topic("  hello   world. "), "Hello world")
        rs = [Reel(id=str(i), url="u", account=f"a{i}", topic=t) for i, t in enumerate(["Trust", "trust", "Other"])]
        topics = group_topics(rs)
        self.assertEqual(sorted(len(t.reels) for t in topics), [1, 2])

    def test_thin_evidence_flag(self):
        one_account = Topic("x", [Reel(id="1", url="u", account="a"), Reel(id="2", url="u", account="a")])
        two_accounts = Topic("y", [Reel(id="1", url="u", account="a"), Reel(id="2", url="u", account="b")])
        self.assertTrue(one_account.thin)
        self.assertFalse(two_accounts.thin)


class ScoringTests(unittest.TestCase):
    def test_combine_redistributes_missing_factors(self):
        full = {k: 80.0 for k in DEFAULT_WEIGHTS}
        score, used = combine(DEFAULT_WEIGHTS, full)
        self.assertAlmostEqual(score, 80.0)
        partial = dict(full, history=None, momentum=None)
        score, used = combine(DEFAULT_WEIGHTS, partial)
        self.assertAlmostEqual(score, 80.0)
        self.assertAlmostEqual(sum(used.values()), 100.0)
        self.assertNotIn("history", used)

    def test_combine_is_not_dragged_down_by_missing_data(self):
        score, _ = combine({"a": 50, "b": 50}, {"a": 90.0, "b": None})
        self.assertAlmostEqual(score, 90.0)

    def test_combine_with_nothing_available(self):
        self.assertEqual(combine({"a": 1}, {"a": None}), (0.0, {}))

    def test_momentum(self):
        self.assertIsNone(momentum_score("x", 100, {}))
        self.assertEqual(momentum_score("new", 100, {"other": 5}), 65.0)
        self.assertAlmostEqual(momentum_score("x", 199, {"X": 99}), 75.0)   # doubled
        self.assertAlmostEqual(momentum_score("x", 99, {"x": 99}), 50.0)    # flat
        self.assertEqual(momentum_score("x", 10 ** 9, {"x": 1}), 100.0)     # clamped
        self.assertEqual(momentum_score("x", 0, {"x": 10 ** 9}), 0.0)

    def test_brand_match_failure_does_not_break_scoring(self):
        class Broken:
            def complete_json(self, system, user):
                raise RuntimeError("boom")
        t = Topic("x", [Reel(id="1", url="u", account="a", heat=50, cta_type="none")])
        score_brand_match([t], Broken(), "brief")
        self.assertIsNone(t.factors["brand_match"])
        self.assertIn("failed", t.notes[0])

    def test_empty_playbook_gives_none(self):
        self.assertIsNone(EmptyPlaybook().history_score("anything"))


class EndToEndSampleTests(unittest.TestCase):
    def run_pipeline(self):
        cfg = TriageConfig(max_age_days=14, min_plays=5000, keep_top=300,
                           spam_terms=["giveaway"], relevance_terms=["brand", "founder", "content", "trust", "post"])
        kept, tstats = triage(load_sample(NOW), cfg, NOW)
        labelled, lstats = label_reels(kept, FakeLLM())
        topics = group_topics(labelled)
        compute_factors(topics, {}, EmptyPlaybook())
        score_brand_match(topics, FakeLLM(), "brief")
        return tstats, lstats, score_topics(topics)

    def test_sample_run(self):
        tstats, lstats, ranked = self.run_pipeline()
        self.assertEqual(tstats["input"], 43)
        self.assertEqual(lstats["errors"], [])
        self.assertEqual(len(ranked), 6)
        names = {t.name for t in ranked}
        self.assertFalse(any("logo" in n.lower() or "giveaway" in n.lower() for n in names))
        scores = [t.score for t in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= s <= 100 for s in scores))
        self.assertTrue(all(t.weights_used and abs(sum(t.weights_used.values()) - 100) < 1e-6 for t in ranked))

    def test_conversion_topic_has_cta_detected(self):
        _, _, ranked = self.run_pipeline()
        conv = next(t for t in ranked if t.name == "Content that converts into leads")
        self.assertTrue(any(r.cta_type == "comment-keyword" for r in conv.reels))


if __name__ == "__main__":
    unittest.main()
