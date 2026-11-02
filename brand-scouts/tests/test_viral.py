import json
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import run_weekly
from scouts.common import Reel
from scouts.frames import Frames, FfmpegFrames, download, extract_frames, ffmpeg_available, frame_times
from scouts.report import render_viral_analysis
from scouts.topics import Topic
from scouts.viral_analysis import (ViralBreakdown, analyse_reel, analyse_topics, build_features, contrasts,
                                   fisher_exact, load_vocab, normalize_breakdown, quote_in, spread, split_groups)

VOCAB = load_vocab()


def reel(i, transcript="Stop doing this. It never works. Do this instead.", heat=50.0, **kw):
    kw.setdefault("plays", 1000)
    return Reel(id=str(i), url=f"https://x/{i}", account=f"acc{i}", transcript=transcript, caption="cap", heat=heat, **kw)


RAW = {"hooks": {"audio": {"text": "Stop doing this.", "type": "contrarian"},
                 "text": {"text": "3 ways", "type": "number-list"},
                 "video": {"description": "close-up face", "type": "face-to-camera"}},
       "hooks_aligned": True, "format": "talking-head", "style": {"tone": "raw", "pacing": "fast"},
       "structure": [{"beat": "hook", "summary": "Stop doing this."}, {"beat": "weird-beat", "summary": "x"}],
       "loop": {"type": "curiosity-gap", "open_loop": "why?", "payoff": "because", "re_hook": "wait for it"},
       "spice": ["specific-number", "pattern-interrupt", "made-up-device", "specific-number"],
       "cta": {"type": "comment-keyword", "text": "Comment GUIDE"}}


class NormalizeTests(unittest.TestCase):
    def test_without_frames_unseen_things_are_discarded_whatever_the_model_said(self):
        bd = normalize_breakdown(RAW, reel(1), VOCAB, n_frames=0)
        self.assertTrue(bd.hooks["audio"]["analysed"])
        self.assertFalse(bd.hooks["text"]["analysed"])
        self.assertFalse(bd.hooks["video"]["analysed"])
        self.assertEqual((bd.hooks["text"]["text"], bd.hooks["video"]["description"]), ("", ""))
        self.assertEqual((bd.format, bd.style["tone"], bd.style["pacing"]), ("unknown", "unknown", "unknown"))
        self.assertNotIn("pattern-interrupt", bd.spice)        # needs frames
        self.assertIsNone(bd.hooks_aligned)                    # only one channel, so alignment is meaningless
        self.assertNotIn("frames", bd.evidence)

    def test_with_frames_everything_is_analysed_and_vocabulary_enforced(self):
        bd = normalize_breakdown(RAW, reel(1), VOCAB, n_frames=4)
        self.assertTrue(all(bd.hooks[c]["analysed"] for c in ("audio", "text", "video")))
        self.assertEqual(bd.format, "talking-head")
        self.assertEqual(bd.spice, ["specific-number", "pattern-interrupt"])    # made-up dropped, duplicate dropped
        self.assertEqual([b["beat"] for b in bd.structure], ["hook", "point"])  # unknown beat -> point
        self.assertTrue(bd.hooks_aligned)
        self.assertIn("frames", bd.evidence)

    def test_no_transcript_means_no_audio_hook(self):
        bd = normalize_breakdown(RAW, reel(1, transcript=""), VOCAB, n_frames=3)
        self.assertFalse(bd.hooks["audio"]["analysed"])

    def test_quote_verification(self):
        self.assertTrue(quote_in("stop  doing THIS", "Stop doing this. It never works."))
        self.assertFalse(quote_in("Never do this", "Stop doing this. It never works."))
        self.assertFalse(quote_in("", "anything"))
        raw = json.loads(json.dumps(RAW))
        raw["hooks"]["audio"]["text"] = "A line the creator never said"
        self.assertFalse(normalize_breakdown(raw, reel(1), VOCAB, 0).hooks["audio"]["verified_quote"])

    def test_unknown_values_become_other(self):
        raw = json.loads(json.dumps(RAW))
        raw["hooks"]["audio"]["type"] = "spooky"
        raw["cta"]["type"] = "telepathy"
        bd = normalize_breakdown(raw, reel(1), VOCAB, 3)
        self.assertEqual(bd.hooks["audio"]["type"], "other")
        self.assertEqual(bd.cta["type"], "none")


class Recorder:
    """Stand-in model that records what it was sent and returns RAW."""
    def __init__(self):
        self.users, self.image_counts = [], []

    def complete_json(self, system, user, images=None):
        self.users.append(user)
        self.image_counts.append(len(images or []))
        return json.loads(json.dumps(RAW))


class OneFrame:
    def frames_for(self, r):
        return Frames([0.0, 1.0], [b"\xff\xd8a", b"\xff\xd8b"])


class AnalyseReelTests(unittest.TestCase):
    def test_the_analyst_is_never_shown_performance(self):
        r = reel(1, followers=123456, plays=987654, likes=4242, comments=777, heat=99.0)
        llm = Recorder()
        analyse_reel(r, llm, VOCAB)
        sent = llm.users[0]
        for forbidden in ("plays", "likes", "comments", "followers", "heat", "987654", "123456", "4242"):
            self.assertNotIn(forbidden, sent)

    def test_images_only_sent_when_frames_exist(self):
        llm = Recorder()
        analyse_reel(reel(1), llm, VOCAB)
        analyse_reel(reel(2), llm, VOCAB, OneFrame())
        self.assertEqual(llm.image_counts, [0, 2])

    def test_model_without_image_support_still_works_for_text_only(self):
        class OldStyle:
            def complete_json(self, system, user):
                return json.loads(json.dumps(RAW))
        self.assertEqual(analyse_reel(reel(1), OldStyle(), VOCAB).error, "")

    def test_failure_is_reported_not_raised(self):
        class Broken:
            def complete_json(self, system, user, images=None):
                raise RuntimeError("api down")
        bd = analyse_reel(reel(1), Broken(), VOCAB)
        self.assertIn("api down", bd.error)
        self.assertEqual(build_features(reel(1), bd, VOCAB), {})


class FeatureTests(unittest.TestCase):
    def test_unknown_is_absent_not_false(self):
        f = build_features(reel(1), normalize_breakdown(RAW, reel(1), VOCAB, 0), VOCAB)
        self.assertTrue(f["hook_audio"])
        self.assertNotIn("hook_text", f)
        self.assertNotIn("all_three_hooks", f)
        self.assertNotIn("format:talking-head", f)
        self.assertNotIn("spice:pattern-interrupt", f)     # cannot be judged without frames

    def test_hook_stack_with_frames(self):
        f = build_features(reel(1, duration_s=22), normalize_breakdown(RAW, reel(1), VOCAB, 4), VOCAB)
        self.assertTrue(f["all_three_hooks"] and f["two_plus_hooks"] and f["hooks_aligned"] and f["re_hook"])
        self.assertTrue(f["hook_audio_type:contrarian"])
        self.assertFalse(f["hook_audio_type:question"])
        self.assertTrue(f["spice_2plus"])
        self.assertFalse(f["spice_3plus"])
        self.assertTrue(f["len:15to30s"])
        self.assertFalse(f["len:under15s"])

    def test_hook_channel_of_type_none_counts_as_unused(self):
        raw = json.loads(json.dumps(RAW))
        raw["hooks"]["text"] = {"text": "", "type": "none"}
        f = build_features(reel(1), normalize_breakdown(raw, reel(1), VOCAB, 4), VOCAB)
        self.assertFalse(f["hook_text"])
        self.assertFalse(f["all_three_hooks"])
        self.assertTrue(f["two_plus_hooks"])


class StatsTests(unittest.TestCase):
    def test_fisher_known_values(self):
        self.assertAlmostEqual(fisher_exact(8, 2, 1, 9), 0.005477, places=5)
        self.assertAlmostEqual(fisher_exact(4, 0, 0, 4), 2 / 70, places=6)
        self.assertAlmostEqual(fisher_exact(3, 3, 3, 3), 1.0)
        self.assertEqual(fisher_exact(0, 0, 0, 0), 1.0)
        self.assertAlmostEqual(fisher_exact(8, 2, 1, 9), fisher_exact(1, 9, 8, 2))

    def test_planted_signal_is_found_and_noise_is_not(self):
        viral = [{"signal": True, "noise": i % 2 == 0, "const": True} for i in range(8)]
        rest = [{"signal": i == 0, "noise": i % 2 == 0, "const": True} for i in range(8)]
        found = {c.feature: c for c in contrasts(viral, rest)}
        self.assertEqual(set(found), {"signal"})          # noise and const have a gap of 0
        self.assertEqual((found["signal"].viral_yes, found["signal"].rest_yes), (8, 1))
        self.assertEqual(found["signal"].read, "likely real")

    def test_small_groups_and_missing_values_are_skipped(self):
        self.assertEqual(contrasts([{"a": True}] * 2, [{"a": False}] * 2, min_group=3), [])
        viral = [{"a": True}] * 3 + [{}] * 5          # feature unknown for 5 of 8
        rest = [{"a": False}] * 3 + [{}] * 5
        c = contrasts(viral, rest, min_group=3)[0]
        self.assertEqual((c.viral_n, c.rest_n), (3, 3))

    def test_benjamini_hochberg_worked_example(self):
        from scouts.viral_analysis import benjamini_hochberg
        q = benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
        for got, want in zip(q, [0.02, 0.04, 0.04, 0.02]):
            self.assertAlmostEqual(got, want)
        self.assertEqual(benjamini_hochberg([]), [])
        self.assertEqual(benjamini_hochberg([0.9]), [0.9])
        self.assertTrue(all(0 <= x <= 1 for x in benjamini_hochberg([0.5, 0.0001, 1.0])))

    def test_testing_many_features_does_not_manufacture_findings(self):
        # Pure noise: 60 coin-flip features, 10 vs 10 Reels. Seed 0 is a case where one feature looks
        # "significant" on its raw p-value alone (checked: ~half of all noise datasets show such a pattern);
        # the correction is what stops us calling it real.
        rnd = random.Random(0)
        viral = [{f"f{k}": rnd.random() < 0.5 for k in range(60)} for _ in range(10)]
        rest = [{f"f{k}": rnd.random() < 0.5 for k in range(60)} for _ in range(10)]
        found = contrasts(viral, rest, min_gap=0.25)
        self.assertTrue(any(c.p < 0.05 for c in found))
        self.assertFalse(any(c.read == "likely real" for c in found))


class GroupTests(unittest.TestCase):
    def topic(self, n_viral, n_peers):
        t = Topic("T", [reel(f"v{i}", heat=90 - i) for i in range(n_viral)])
        t.peers = [reel(f"p{i}", heat=20 - i) for i in range(n_peers)]
        return t, {r.id for r in t.reels + t.peers}

    def test_peers_are_preferred(self):
        t, have = self.topic(5, 4)
        v, r, basis = split_groups(t, have)
        self.assertTrue(basis.startswith("viral Reels vs non-viral"))
        self.assertEqual((len(v), len(r)), (5, 4))

    def test_falls_back_to_within_viral(self):
        t, have = self.topic(7, 1)
        v, r, basis = split_groups(t, have)
        self.assertIn("top third", basis)
        self.assertEqual((len(v), len(r)), (2, 2))
        t, have = self.topic(4, 0)
        self.assertIn("top half", split_groups(t, have)[2])

    def test_too_few_still_returns_the_viral_reels_for_description(self):
        t, have = self.topic(2, 0)
        v, r, basis = split_groups(t, have)
        self.assertEqual((len(v), r), (2, []))
        self.assertIn("no comparison possible", basis)

    def test_only_analysed_reels_count(self):
        t, have = self.topic(5, 4)
        v, r, basis = split_groups(t, have - {"p0"})          # 3 peers left: still enough
        self.assertEqual((len(r), basis[:12]), (3, "viral Reels "))
        v, r, basis = split_groups(t, have - {"p0", "p1"})     # 2 peers left: too few, so fall back
        self.assertIn("top half", basis)
        self.assertTrue(all(x.id.startswith("v") for x in r))

    def test_spread_covers_the_range(self):
        self.assertEqual(spread(list(range(10)), 5), [0, 2, 4, 6, 8])
        self.assertEqual(spread([1, 2], 5), [1, 2])


class Scripted:
    """Viral Reels (ids starting 'v') get a richer presentation than peers ('p')."""
    def __init__(self, fail_ids=()):
        self.explain_calls, self.fail_ids, self.users = 0, set(fail_ids), []

    def complete_json(self, system, user, images=None):
        data = json.loads(user)
        if "[TASK:breakdown]" in system:
            self.users.append(user)
            rid = data["reel"]["id"]
            if rid in self.fail_ids:
                raise RuntimeError("boom")
            viral = rid.startswith("v")
            raw = json.loads(json.dumps(RAW))
            if not viral:
                raw["hooks"]["audio"]["type"] = "bold-claim"
                raw["hooks"]["text"] = {"text": "", "type": "none"}
                raw["hooks"]["video"] = {"description": "", "type": "none"}
                raw["hooks_aligned"], raw["spice"] = None, []
                raw["loop"] = {"type": "none", "open_loop": "", "payoff": "", "re_hook": None}
                raw["cta"] = {"type": "none", "text": ""}
            return raw
        if "[TASK:explain]" in system:
            self.explain_calls += 1
            return {"summary": "explained", "what_to_copy": ["all_three_hooks"], "what_not_to_copy": [], "template": "t", "caveats": []}
        raise ValueError(system[:20])


class AnalyseTopicsTests(unittest.TestCase):
    def topics(self):
        t1 = Topic("T1", [reel(f"v{i}", heat=90 - i) for i in range(4)])
        t1.peers = [reel(f"p{i}", heat=20 - i) for i in range(4)]
        t2 = Topic("T2", [reel(f"v2{i}", heat=80 - i) for i in range(5)])
        t2.peers = [reel("p20", heat=10)]
        t3 = Topic("T3", [reel("v30"), reel("v31")])
        return [t1, t2, t3]

    def run_it(self, llm=None, frames=None):
        llm = llm or Scripted()
        return llm, analyse_topics(self.topics(), llm, VOCAB, "brief", frames, min_group=3)

    def test_topic_comparison_finds_the_planted_difference(self):
        llm, va = self.run_it(frames=OneFrame())
        t1 = va.topics[0]
        self.assertTrue(t1.basis.startswith("viral Reels vs"))
        found = {c.feature: c for c in t1.contrasts}
        self.assertEqual((found["all_three_hooks"].viral_yes, found["all_three_hooks"].rest_yes), (4, 0))
        self.assertNotEqual(found["hook_audio_type:contrarian"].read, "weak")
        self.assertEqual(t1.explanation["summary"], "explained")

    def test_pooled_comparison_is_matched_per_topic(self):
        _, va = self.run_it(frames=OneFrame())
        # T1 contributes 4 vs 4, T2 contributes min(5, 1) = 1 vs 1, T3 has no peers. 5 vs 5, not 9 vs 5.
        self.assertEqual(va.pooled_n, (5, 5))
        self.assertIn("matched per topic", va.pooled_basis)

    def test_no_explanation_call_without_a_contrast(self):
        llm, va = self.run_it(frames=OneFrame())
        self.assertEqual(llm.explain_calls, 1)               # only T1 had a usable comparison
        self.assertEqual(va.topics[2].explanation, {})
        self.assertIn("no comparison possible", va.topics[2].basis)
        self.assertEqual(len(va.topics[2].viral_ids), 2)      # but its Reels are still described

    def test_one_failed_reel_is_counted_and_the_rest_continue(self):
        _, va = self.run_it(llm=Scripted(fail_ids=["v0"]), frames=OneFrame())
        self.assertEqual(va.coverage["failed"], 1)
        self.assertIn("boom", va.coverage["errors"][0])
        self.assertNotIn("v0", va.features)
        self.assertEqual(va.coverage["reels_analysed"], len(va.breakdowns) - 1)

    def test_coverage_without_frames_says_so(self):
        _, va = self.run_it()
        self.assertEqual((va.coverage["with_frames"], va.coverage["text_hook_analysed"], va.coverage["video_hook_analysed"]), (0, 0, 0))
        self.assertGreater(va.coverage["audio_hook_analysed"], 0)

    def test_max_reels_caps_cost(self):
        llm = Scripted()
        va = analyse_topics(self.topics(), llm, VOCAB, "brief", None, max_reels=5)
        self.assertEqual(len(va.breakdowns), 5)

    def test_report_renders_with_warnings_and_gaps(self):
        _, va = self.run_it()
        va.breakdowns["v0"].hooks["audio"]["verified_quote"] = False
        va.breakdowns["v0"].hooks["audio"]["text"] = "invented line"
        reels = {r.id: r for t in self.topics() for r in t.reels + t.peers}
        md = render_viral_analysis(va, self.topics(), reels, "2026-10-17", sample=False)
        self.assertIn("not analysed", md)
        self.assertIn("⚠️", md)
        self.assertIn("without seeing its view count", md)
        self.assertNotIn("SAMPLE RUN", md)
        self.assertIn("## 3. T3", md)


@unittest.skipUnless(ffmpeg_available(), "ffmpeg not installed")
class FrameTests(unittest.TestCase):
    def test_extracts_jpegs_at_the_requested_seconds(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "t.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=10",
                            "-pix_fmt", "yuv420p", str(v)], check=True)
            fr = extract_frames(v, frame_times(8.0))
            self.assertEqual(fr.times, [0.0, 1.0, 2.0, 3.0, 5.6])
            self.assertTrue(all(img[:2] == b"\xff\xd8" for img in fr.images))


class FrameLogicTests(unittest.TestCase):
    def test_frame_times(self):
        self.assertEqual(frame_times(None), [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(frame_times(2.0), [0.0, 1.0])
        self.assertEqual(frame_times(8.0), [0.0, 1.0, 2.0, 3.0, 5.6])
        self.assertEqual(frame_times(30.0), [0.0, 1.0, 2.0, 3.0, 10.5, 21.0])

    def test_download_refuses_non_https(self):
        with self.assertRaises(ValueError):
            download("file:///etc/passwd", Path("/tmp/never"))
        with self.assertRaises(ValueError):
            download("http://example.com/v.mp4", Path("/tmp/never"))

    def test_no_video_url_means_no_frames_not_an_error(self):
        self.assertEqual(FfmpegFrames().frames_for(reel(1)).images, [])


class EndToEnd(unittest.TestCase):
    def test_sample_run_writes_the_viral_analysis(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(StringIO()):
            self.assertEqual(run_weekly.main(["--sample", "--out", d]), 0)
            out = Path(d)
            md = (out / "viral_analysis.md").read_text()
            data = json.loads((out / "viral_analysis.json").read_text())
            self.assertIn("SAMPLE RUN", md)
            self.assertIn("not analysed", md)
            self.assertIn("without seeing its view count", md)
            self.assertGreater(len(data["breakdowns"]), 0)
            self.assertEqual(data["pooled"]["n"][0], data["pooled"]["n"][1])


if __name__ == "__main__":
    unittest.main()
