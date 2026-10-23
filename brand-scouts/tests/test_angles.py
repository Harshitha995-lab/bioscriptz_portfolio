import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import run_weekly
from scouts.angles import AngleIdea, angle_baselines, expand_angles, load_angles, shortlist
from scouts.common import ROOT, Reel
from scouts.fake_llm import FakeLLM
from scouts.playbook import EmptyPlaybook
from scouts.topics import Topic

ANGLES = {"story": "s", "contrarian": "c", "proof": "p"}


def reel(i, account, angle, heat):
    return Reel(id=str(i), url=f"u{i}", account=account, plays=1000, heat=heat, angle=angle, topic="t")


def two_topics():
    a = Topic("A", [reel(1, "x", "story", 80), reel(2, "y", "story", 60)])
    b = Topic("B", [reel(3, "z", "story", 40), reel(4, "w", "contrarian", 30)])
    for t in (a, b):
        t.score = 50
    return a, b


class FixedLLM:
    def __init__(self, fit=70, omit=(), fail=False):
        self.fit, self.omit, self.fail = fit, set(omit), fail

    def complete_json(self, system, user):
        if self.fail:
            raise RuntimeError("down")
        names = [a["name"] for a in json.loads(user)["angles"] if a["name"] not in self.omit]
        return {"angles": [{"angle": n, "pitch": f"p-{n}", "hook": f"h-{n}", "fit": self.fit, "reason": "r"} for n in names]}


class ExpandTests(unittest.TestCase):
    def test_baselines(self):
        a, b = two_topics()
        self.assertEqual(angle_baselines([a, b]), {"story": 60, "contrarian": 30})

    def test_evidence_shrinks_toward_baseline(self):
        a, b = two_topics()
        ideas = {(i.topic, i.angle): i for i in expand_angles([a, b], FixedLLM(), ANGLES, "brief", EmptyPlaybook())}
        self.assertAlmostEqual(ideas[("A", "story")].evidence, (80 + 60 + 2 * 60) / 4)   # 65
        self.assertEqual(ideas[("A", "story")].kind, "proven")

    def test_untested_angle_gets_the_prior_not_a_bonus(self):
        a, b = two_topics()
        ideas = {(i.topic, i.angle): i for i in expand_angles([a, b], FixedLLM(), ANGLES, "brief", EmptyPlaybook())}
        untested = ideas[("A", "contrarian")]
        self.assertEqual(untested.kind, "experiment")
        self.assertEqual(untested.evidence, 30)                     # the angle's weekly average, nothing more
        no_data_anywhere = ideas[("A", "proof")]
        self.assertEqual((no_data_anywhere.baseline, no_data_anywhere.evidence), (None, 50.0))

    def test_proven_angle_beats_untested_only_when_above_its_average(self):
        a, b = two_topics()
        ideas = {(i.topic, i.angle): i for i in expand_angles([a, b], FixedLLM(fit=70), ANGLES, "brief", EmptyPlaybook())}
        self.assertGreater(ideas[("A", "story")].score, ideas[("B", "story")].score)   # 65 vs 50 evidence, same fit

    def test_fit_failure_redistributes_weight(self):
        a, _ = two_topics()
        ideas = expand_angles([a], FixedLLM(fail=True), ANGLES, "brief", EmptyPlaybook())
        self.assertTrue(all(i.fit is None and "fit" not in i.weights_used for i in ideas))
        self.assertIn("failed", ideas[0].fit_reason)
        self.assertAlmostEqual(sum(ideas[0].weights_used.values()), 100.0)

    def test_omitted_angle_has_no_pitch(self):
        a, _ = two_topics()
        ideas = {i.angle: i for i in expand_angles([a], FixedLLM(omit=["proof"]), ANGLES, "brief", EmptyPlaybook())}
        self.assertEqual(ideas["proof"].pitch, "")
        self.assertEqual(ideas["story"].pitch, "p-story")

    def test_fit_is_clamped_and_garbage_ignored(self):
        class Odd:
            def complete_json(self, s, u):
                return {"angles": [{"angle": "story", "pitch": "p", "fit": 250}, {"angle": "contrarian", "pitch": "p", "fit": "abc"}]}
        a, _ = two_topics()
        ideas = {i.angle: i for i in expand_angles([a], Odd(), ANGLES, "brief", EmptyPlaybook())}
        self.assertEqual(ideas["story"].fit, 100.0)
        self.assertIsNone(ideas["contrarian"].fit)

    def test_load_angles(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("// c\nstory: a tale\nhow-to: steps: one, two\n")
            self.assertEqual(load_angles(p), {"story": "a tale", "how-to": "steps: one, two"})


def idea(topic, angle, score, n=1, pitch="p"):
    return AngleIdea(topic=topic, angle=angle, pitch=pitch, evidence_n=n, score=score)


def topic(name, score, accounts=2):
    t = Topic(name, [Reel(id=f"{name}{i}", url="u", account=f"acc{i}") for i in range(accounts)])
    t.score = score
    return t


class ShortlistTests(unittest.TestCase):
    def six(self, untested_in=()):
        topics = [topic(f"T{i}", 90 - i * 10) for i in range(6)]
        ideas = [idea(t.name, a, 80 - j * 5, n=0 if t.name in untested_in else 1)
                 for t in topics for j, a in enumerate(["a1", "a2", "a3", "a4", "a5"])]
        return topics, ideas

    def test_four_data_one_experiment_max_three_angles(self):
        topics, ideas = self.six(untested_in=["T4", "T5"])
        picks, notes = shortlist(topics, ideas, 5, 3, 1)
        self.assertEqual([p.slot for p in picks], ["data"] * 4 + ["experiment"])
        self.assertEqual([p.topic.name for p in picks[:4]], ["T0", "T1", "T2", "T3"])
        self.assertTrue(all(len(p.angles) <= 3 for p in picks))
        self.assertEqual(notes, [])

    def test_experiment_slot_prefers_untested_angles(self):
        topics, ideas = self.six(untested_in=["T5"])
        picks, _ = shortlist(topics, ideas, 5, 3, 1)
        self.assertEqual(picks[-1].topic.name, "T5")
        self.assertTrue(all(a.kind == "experiment" for a in picks[-1].angles))

    def test_thin_topic_can_fill_the_experiment_slot(self):
        topics, ideas = self.six()
        topics[5] = topic("T5", 40, accounts=1)
        picks, _ = shortlist(topics, ideas, 5, 3, 1)
        self.assertEqual((picks[-1].slot, picks[-1].topic.name), ("experiment", "T5"))

    def test_no_experiment_available_is_reported_not_faked(self):
        topics, ideas = self.six()                       # everything proven, nothing thin
        picks, notes = shortlist(topics, ideas, 5, 3, 1)
        self.assertEqual(len(picks), 5)
        self.assertTrue(all(p.slot == "data" for p in picks))
        self.assertIn("no experiment", notes[0].lower())

    def test_small_inputs(self):
        topics, ideas = self.six()
        one, notes = shortlist(topics[:1], [i for i in ideas if i.topic == "T0"], 5, 3, 1)
        self.assertEqual([p.slot for p in one], ["data"])
        self.assertTrue(notes)
        none, _ = shortlist([], [], 5, 3, 1)
        self.assertEqual(none, [])

    def test_incomplete_angles_are_skipped_when_complete_ones_exist(self):
        t = topic("T", 50)
        ideas = [idea("T", "a", 99, pitch=""), idea("T", "b", 10), idea("T", "c", 20)]
        picks, _ = shortlist([t], ideas, 5, 3, 1)
        self.assertEqual([a.angle for a in picks[0].angles], ["c", "b"])


class EndToEndTests(unittest.TestCase):
    def test_sample_run_writes_shortlist(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(StringIO()):
            self.assertEqual(run_weekly.main(["--sample", "--out", d]), 0)
            out = Path(d)
            for name in ("shortlist.md", "shortlist.json", "angles.json", "topics.json", "top10.md", "reels.json"):
                self.assertTrue((out / name).exists(), name)
            picks = json.loads((out / "shortlist.json").read_text())
            self.assertEqual(len(picks), 5)
            self.assertEqual(sum(p["slot"] == "experiment" for p in picks), 1)
            allowed = set(load_angles(ROOT / "config" / "angles.txt"))
            ideas = json.loads((out / "angles.json").read_text())
            n_topics = len(json.loads((out / "topics.json").read_text()))
            self.assertGreaterEqual(n_topics, 5)
            self.assertEqual(len(ideas), min(n_topics, 10) * len(allowed))
            self.assertTrue({i["angle"] for i in ideas} <= allowed)
            md = (out / "shortlist.md").read_text()
            self.assertIn("SAMPLE RUN", md)
            self.assertIn("EXPERIMENT", md)


if __name__ == "__main__":
    unittest.main()
