import json
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import run_weekly
from scouts.frames import ffmpeg_available
from scouts.library import (feature_changes, find_twins, pair_patterns, run_library, select_library, sign_test_p)
from scouts.report import render_library
from scouts.common import Reel
from scouts.transcribe import LazyTranscriber, ensure_transcripts
from scouts.viral_analysis import load_vocab

VOCAB = load_vocab()


def mk(i, account=None, keyword="k", topic="T", heat=50.0, plays=1000, **kw):
    return Reel(id=str(i), url=f"https://x/{i}", account=account or f"acc{i}", keyword=keyword, topic=topic, heat=heat, plays=plays,
                transcript=kw.pop("transcript", "Stop doing this. It never works. Do this instead."), **kw)


class SelectTests(unittest.TestCase):
    def test_round_robin_with_keyword_cap(self):
        reels = ([mk(f"a{i}", keyword="k1", heat=100 - i) for i in range(10)]
                 + [mk(f"b{i}", keyword="k2", heat=50 - i) for i in range(3)] + [mk("c0", keyword="k3", heat=10)])
        picked, info = select_library(reels, n=8, per_keyword_cap=4, per_account_cap=2)
        counts = {k: sum(r.keyword == k for r in picked) for k in ("k1", "k2", "k3")}
        self.assertEqual(counts, {"k1": 4, "k2": 3, "k3": 1})
        self.assertEqual(info["keywords_covered"], 3)
        picked, info = select_library(reels, n=100, per_keyword_cap=4, per_account_cap=2)
        self.assertEqual(info["selected"], 8)                      # cap limits it, and says so rather than padding

    def test_best_keyword_does_not_crowd_out_the_others(self):
        reels = [mk(f"a{i}", keyword="hot", heat=99) for i in range(50)] + [mk("z", keyword="quiet", heat=5)]
        picked, _ = select_library(reels, n=10, per_keyword_cap=5, per_account_cap=2)
        self.assertIn("z", {r.id for r in picked})

    def test_per_account_cap(self):
        reels = [mk(f"a{i}", account="same", keyword=f"k{i}", heat=90 - i) for i in range(6)] + [mk("o", account="other", keyword="k9", heat=1)]
        picked, _ = select_library(reels, n=10, per_keyword_cap=5, per_account_cap=2)
        self.assertEqual(sum(r.account == "same" for r in picked), 2)
        self.assertIn("o", {r.id for r in picked})

    def test_unknown_keyword_groups_by_topic(self):
        reels = [mk(i, keyword="", topic="T1", heat=90 - i) for i in range(6)] + [mk("x", keyword="", topic="T2", heat=1)]
        picked, info = select_library(reels, n=4, per_keyword_cap=2, per_account_cap=2)
        self.assertEqual(sorted(r.topic for r in picked), ["T1", "T1", "T2"])
        self.assertEqual(info["keywords_available"], 2)

    def test_empty(self):
        self.assertEqual(select_library([], 100, 5, 2)[0], [])


class TwinTests(unittest.TestCase):
    def pool(self):
        return [mk("w", account="Ann", plays=6_100_000), mk("m", account="ann", plays=42_000), mk("n", account="ANN", plays=300_000),
                mk("near", account="ann", plays=700_000)]

    def test_nearest_miss_at_least_10x_lower_is_the_baseline(self):
        pool = self.pool()
        pairs = find_twins(pool, [pool[0]], min_ratio=10)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].baseline.id, "n")                  # 300k beats 42k as "closest miss"; 700k is only 8.7x so excluded
        self.assertAlmostEqual(pairs[0].ratio, 6_100_000 / 300_000)

    def test_exactly_the_user_example(self):
        w, b = mk("w", account="x", plays=6_100_000), mk("b", account="x", plays=42_000)
        (pair,) = find_twins([w, b], [w])
        self.assertAlmostEqual(pair.ratio, 145.2, places=1)

    def test_other_topic_other_account_tiny_and_unknown_are_excluded(self):
        w = mk("w", account="a", plays=1_000_000)
        others = [mk("t", account="a", topic="Other", plays=1000), mk("c", account="b", plays=1000), mk("tiny", account="a", plays=500)]
        self.assertEqual(find_twins([w] + others, [w]), [])
        unk = mk("u", account="unknown", plays=1_000_000)
        self.assertEqual(find_twins([unk, mk("u2", account="unknown", plays=1000)], [unk]), [])
        self.assertEqual(find_twins([mk("nt", account="a", topic="", plays=9_000_000), mk("nt2", account="a", topic="", plays=1000)], []), [])

    def test_baseline_order(self):
        from datetime import datetime, timezone
        w = mk("w", account="a", plays=1_000_000, posted_at=datetime(2026, 10, 10, tzinfo=timezone.utc))
        b = mk("b", account="a", plays=1000, posted_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertTrue(find_twins([w, b], [w])[0].baseline_came_first)
        b.posted_at = None
        self.assertIsNone(find_twins([w, b], [w])[0].baseline_came_first)


class PatternTests(unittest.TestCase):
    def test_feature_changes_only_counts_what_both_could_be_judged_on(self):
        win = {"a": True, "b": False, "c": True}
        base = {"a": False, "b": True, "c": True, "d": True}
        self.assertEqual(feature_changes(win, base), (["a"], ["b"]))

    def test_sign_test(self):
        self.assertEqual(sign_test_p(0, 0), 1.0)
        self.assertEqual(sign_test_p(3, 3), 1.0)
        self.assertAlmostEqual(sign_test_p(4, 0), 0.125)
        self.assertAlmostEqual(sign_test_p(6, 0), 0.03125)
        self.assertAlmostEqual(sign_test_p(5, 1), 0.21875)
        self.assertEqual(sign_test_p(2, 5), sign_test_p(5, 2))

    def test_you_need_about_six_consistent_pairs(self):
        four = pair_patterns([(["x"], [])] * 4)
        self.assertEqual(four[0].read, "weak")                       # four out of four is still not enough
        six = pair_patterns([(["x"], [])] * 6)
        self.assertEqual(six[0].read, "likely real")

    def test_rare_changes_are_not_reported(self):
        self.assertEqual(pair_patterns([(["x"], []), (["x"], [])], min_changed=3), [])

    def test_mixed_directions_are_not_a_pattern(self):
        rows = pair_patterns([(["x"], [])] * 3 + [([], ["x"])] * 3)
        self.assertEqual(rows[0].read, "weak")


class LibLLM:
    """Labels from a 'topic:NAME' marker in the caption; winners ('w...') are richly presented, baselines ('b...') plain."""
    def __init__(self):
        self.breakdown_ids, self.pair_calls = [], 0

    def complete_json(self, system, user, images=None):
        data = json.loads(user)
        if "[TASK:label]" in system:
            labels = []
            for r in data["reels"]:
                m = re.search(r"topic:(\w+)", r["caption"])
                labels.append({"id": r["id"], "relevant": bool(m), "topic": m.group(1) if m else "", "angle": "story", "cta_type": "none", "hook": ""})
            return {"labels": labels}
        if "[TASK:breakdown]" in system:
            rid = data["reel"]["id"]
            self.breakdown_ids.append(rid)
            rich = rid.startswith("w")
            return {"hooks": {"audio": {"text": "Stop doing this.", "type": "contrarian" if rich else "bold-claim"},
                              "text": {"text": "", "type": "none"}, "video": {"description": "", "type": "none"}},
                    "format": "talking-head", "style": {}, "structure": [{"beat": "hook", "summary": "x"}],
                    "loop": {"type": "curiosity-gap" if rich else "none", "open_loop": "", "payoff": "", "re_hook": None},
                    "spice": ["specific-number"] if rich else [], "cta": {"type": "none", "text": ""}}
        if "[TASK:explain_pair]" in system:
            self.pair_calls += 1
            return {"what_changed": "it changed", "worth_testing": ["loop:curiosity-gap"], "template": "[hook]", "caveats": ["One pair cannot prove cause."]}
        raise ValueError(system[:25])


CFG = {"n": 10, "per_keyword_cap": 5, "per_account_cap": 2, "transcribe_missing": False, "twin_search": True, "twin_min_ratio": 10,
       "twin_min_baseline_plays": 1000, "followup_per_account": 15, "min_pairs_for_pattern": 3}


def winners(n=8):
    return [mk(f"w{i}", account=f"acc{i}", keyword=f"k{i % 4}", topic="T", heat=90 - i, plays=1_000_000, caption=f"topic:T") for i in range(n)]


def loader(accounts):
    out = [mk(f"b{a}", account=a, plays=20_000, caption="topic:T", transcript="Today a few words.") for a in accounts]
    out += [mk(f"off{a}", account=a, plays=20_000, caption="no marker", transcript="Unrelated.") for a in accounts]   # other topic
    out += [mk(f"low{a}", account=a, plays=300, caption="topic:T") for a in accounts]                               # below min plays
    return out


class RunLibraryTests(unittest.TestCase):
    def run_it(self, **kw):
        llm = LibLLM()
        res = run_library(winners(), [], llm, VOCAB, "brief", ["story"], CFG, followups_loader=kw.pop("loader", loader), **kw)
        return llm, res

    def test_finds_pairs_and_a_consistent_change(self):
        llm, res = self.run_it()
        self.assertEqual(len(res.twins), 8)
        self.assertTrue(all(t["pair"].baseline.id.startswith("b") for t in res.twins))      # off-topic and tiny Reels never become baselines
        self.assertEqual(res.followups["fetched"], 16)                                        # 8 matching + 8 off-topic; 8 tiny dropped before labelling
        self.assertEqual(res.followups["matched"], 8)
        top = {p.feature: p for p in res.patterns}
        self.assertEqual(top["loop:curiosity-gap"].read, "likely real")                       # 8 of 8 pairs changed the same way
        self.assertEqual(llm.pair_calls, 8)

    def test_one_pair_per_creator_in_statistics(self):
        ws = winners(4) + [mk("w_extra", account="acc0", keyword="k9", topic="T2", heat=70, plays=1_000_000, caption="topic:T2")]
        def ld(accounts):
            return [mk(f"b{a}", account=a, plays=20_000, caption="topic:T") for a in accounts] + [mk("b_extra", account="acc0", plays=20_000, caption="topic:T2")]
        res = run_library(ws, [], LibLLM(), VOCAB, "brief", ["story"], CFG, followups_loader=ld)
        self.assertEqual(len(res.twins), 5)                                    # all five pairs are shown to the reader...
        self.assertEqual(res.selection["pairs_in_statistics"], 4)
        top = {p.feature: p for p in res.patterns}
        self.assertEqual(top["loop:curiosity-gap"].added, 4)                  # ...but acc0 counts once in the pattern statistics

    def test_existing_breakdowns_are_reused(self):
        from scouts.viral_analysis import analyse_reels
        ws = winners(3)
        pre = analyse_reels(ws[:1], LibLLM(), VOCAB)
        llm = LibLLM()
        run_library(ws, [], llm, VOCAB, "brief", ["story"], CFG, followups_loader=loader, breakdowns=pre)
        self.assertNotIn("w0", llm.breakdown_ids)

    def test_loader_failure_is_reported_not_raised(self):
        def bad(accounts):
            raise RuntimeError("apify down")
        _, res = self.run_it(loader=bad)
        self.assertIn("apify down", res.followups["error"])
        self.assertEqual(res.twins, [])
        self.assertEqual(len(res.reels), 8)                                                   # the library itself still works

    def test_no_loader_means_no_pairs_and_an_honest_report(self):
        res = run_library(winners(), [], LibLLM(), VOCAB, "brief", ["story"], CFG, followups_loader=None)
        self.assertEqual(res.twins, [])
        md = render_library(res, "2026-10-17", sample=False)
        self.assertIn("0 usable pair(s)", md)
        self.assertIn("Description only", md)

    def test_report_contents(self):
        _, res = self.run_it()
        md = render_library(res, "2026-10-17", sample=False)
        self.assertIn("<details><summary>Full transcript</summary>", md)
        self.assertIn("Same creator, same topic, earlier version", md)
        self.assertIn("One pair cannot prove cause", md)
        self.assertIn("without the analyst seeing its view count", md)
        self.assertNotIn("SAMPLE RUN", md)
        self.assertIn("SAMPLE RUN", render_library(res, "2026-10-17", sample=True))

    def test_report_says_when_fewer_than_requested(self):
        _, res = self.run_it()
        md = render_library(res, "2026-10-17", sample=False)
        self.assertIn("needs at least 2 keywords", md)                                        # n=10 at 5 per keyword

    def test_missing_transcript_is_stated_not_hidden(self):
        ws = winners(2)
        ws[0].transcript = ""
        res = run_library(ws, [], LibLLM(), VOCAB, "brief", ["story"], CFG, followups_loader=None)
        self.assertIn("Transcript not available", render_library(res, "2026-10-17", sample=False))


class TranscribeTests(unittest.TestCase):
    class Stub:
        def transcribe(self, path):
            return " spoken words "

    def test_counts_and_reasons(self):
        have, nourl, needs = mk(1, transcript="already"), mk(2, transcript=""), mk(3, transcript="", video_url="https://v/3.mp4")
        stats = ensure_transcripts([have, nourl, needs], None)
        self.assertEqual((stats["already_had"], stats["skipped"]), (1, 2))
        self.assertIn("no transcriber", stats["reason"])
        self.assertEqual(needs.transcript, "")

    @unittest.skipUnless(ffmpeg_available(), "ffmpeg not installed")
    def test_transcribes_through_a_real_audio_track(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-f", "lavfi", "-i",
                            "testsrc=duration=3:size=160x120:rate=10", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
            with mock.patch("scouts.transcribe.download", side_effect=lambda url, dest, **k: shutil.copy(src, dest)):
                r = mk(1, transcript="", video_url="https://v/1.mp4")
                stats = ensure_transcripts([r], self.Stub())
        self.assertEqual((r.transcript, stats["transcribed"], stats["failed"]), ("spoken words", 1, 0))

    @unittest.skipUnless(ffmpeg_available(), "ffmpeg not installed")
    def test_silent_video_counts_as_failed(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "silent.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10", "-pix_fmt", "yuv420p", str(src)], check=True)
            with mock.patch("scouts.transcribe.download", side_effect=lambda url, dest, **k: shutil.copy(src, dest)):
                r = mk(1, transcript="", video_url="https://v/1.mp4")
                stats = ensure_transcripts([r], self.Stub())
        self.assertEqual((r.transcript, stats["failed"]), ("", 1))

    @unittest.skipUnless(ffmpeg_available(), "ffmpeg not installed")
    def test_engine_failure_keeps_the_first_cause(self):
        def boom():
            raise ImportError("faster_whisper missing")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "a.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
                            "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
            with mock.patch("scouts.transcribe.download", side_effect=lambda url, dest, **k: shutil.copy(src, dest)):
                stats = ensure_transcripts([mk(1, transcript="", video_url="https://v/1.mp4")], LazyTranscriber(boom))
        self.assertEqual(stats["failed"], 1)
        self.assertIn("faster_whisper missing", stats["error"])

    def test_max_reels_limit(self):
        rs = [mk(i, transcript="", video_url=f"https://v/{i}.mp4") for i in range(5)]
        with mock.patch("scouts.transcribe.download", side_effect=RuntimeError("no net")), mock.patch("scouts.transcribe.ffmpeg_available", return_value=True):
            stats = ensure_transcripts(rs, self.Stub(), max_reels=2)
        self.assertEqual((stats["failed"], stats["skipped"]), (2, 3))


class EndToEnd(unittest.TestCase):
    def test_sample_run_writes_the_library(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(StringIO()):
            self.assertEqual(run_weekly.main(["--sample", "--out", d]), 0)
            out = Path(d)
            data = json.loads((out / "viral_reels.json").read_text())
            md = (out / "viral_reels.md").read_text()
            self.assertGreater(len(data["reels"]), 0)
            self.assertLessEqual(len(data["reels"]), 100)
            self.assertTrue(all(r["transcript"] for r in data["reels"]))
            self.assertGreater(len(data["twins"]), 0)
            self.assertTrue(all(t["ratio"] >= 10 for t in data["twins"]))
            kws = {r["keyword"] for r in data["reels"]}
            self.assertGreaterEqual(len(kws), 2)
            self.assertIn("SAMPLE RUN", md)
            self.assertIn("<details>", md)


if __name__ == "__main__":
    unittest.main()
