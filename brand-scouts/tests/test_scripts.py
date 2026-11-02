import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import run_weekly
from scouts.common import Reel
from scouts.frameworks import Evidence, pick_framework, scoreboard, uses
from scouts.script_run import choose_references, generate_scripts, reference_brief
from scouts.scriptwriter import (CHECKS, SCRIPT_SYSTEM, Script, check_script, is_subsequence, longest_shared_run, norm_words,
                                 normalize_script, unsourced_numbers, write_script)
from scouts.viral_analysis import load_vocab
from scouts.watchlist import append_snapshot, baselines, known_reels, load_history, outlier_feed

VOCAB = load_vocab()
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def reel(i, account="a", plays=1000, days=3, **kw):
    return Reel(id=str(i), url=f"https://x/{i}", account=account, plays=plays, posted_at=NOW - timedelta(days=days), **kw)


# ----------------------------------------------------------------------------- watchlist

class WatchlistTests(unittest.TestCase):
    def test_snapshot_roundtrip_and_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "w.jsonl"
            append_snapshot(path, [reel(1, plays=100)], NOW - timedelta(days=7))
            append_snapshot(path, [reel(1, plays=900), reel(2, plays=5)], NOW)
            with open(path, "a") as fh:
                fh.write("not json\n{\"id\": 3}\n")
            hist = load_history(path)
            self.assertEqual([r["plays"] for r in hist["1"]], [100, 900])      # oldest first
            self.assertEqual(set(hist), {"1", "2"})                              # corrupt and incomplete lines skipped
            self.assertEqual(load_history(Path(d) / "missing.jsonl"), {})

    def test_this_run_overrides_history(self):
        hist = {"1": [{"seen": "2026-10-01", "account": "a", "plays": 100, "posted_at": None}]}
        self.assertEqual(known_reels(hist, [reel(1, plays=700)])["1"]["plays"], 700)

    def test_baseline_needs_enough_reels_and_is_robust_to_one_hit(self):
        known = {str(i): {"account": "A", "plays": p, "posted_at": NOW - timedelta(days=i)} for i, p in enumerate([1000, 1100, 900, 1050, 50_000])}
        self.assertEqual(baselines(known, ["a"], min_reels=5), {"a": 1050.0})
        self.assertEqual(baselines(known, ["a"], min_reels=6), {})
        self.assertEqual(baselines(known, ["nobody"], min_reels=1), {})

    def test_baseline_uses_only_the_most_recent_reels(self):
        known = {str(i): {"account": "a", "plays": 100 if i < 5 else 9_000, "posted_at": NOW - timedelta(days=i)} for i in range(10)}
        self.assertEqual(baselines(known, ["a"], min_reels=3, recent=5)["a"], 100.0)

    def regulars(self, n=6, plays=1000):
        return [reel(f"r{i}", plays=plays, days=10 + i) for i in range(n)]

    def test_outlier_is_flagged_against_the_creators_own_usual(self):
        pool = self.regulars() + [reel("hit", plays=6_100_000 // 100, days=2)]
        rows, table, base = outlier_feed(pool, {}, ["A"], k=3, now=NOW)       # handle case differs on purpose
        self.assertEqual([w.reel.id for w in rows], ["hit"])
        self.assertAlmostEqual(rows[0].ratio, 61.0)
        self.assertEqual(table["A"]["outliers"], 1)

    def test_not_flagged_without_a_baseline_when_old_or_below_k(self):
        few = [reel(i, plays=1000, days=10 + i) for i in range(3)] + [reel("hit", plays=90_000)]
        self.assertEqual(outlier_feed(few, {}, ["a"], now=NOW)[0], [])          # only 4 Reels: no "usual" yet
        pool = self.regulars() + [reel("old", plays=50_000, days=90), reel("meh", plays=2500, days=1)]
        rows, *_ = outlier_feed(pool, {}, ["a"], k=3, max_age_days=30, now=NOW)
        self.assertEqual(rows, [])

    def test_unwatched_accounts_are_ignored(self):
        pool = self.regulars() + [reel("x", account="stranger", plays=900_000)]
        self.assertEqual(outlier_feed(pool, {}, ["a"], now=NOW)[0], [])

    def test_history_supplies_the_missing_baseline_and_growth(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "w.jsonl"
            append_snapshot(path, self.regulars(5) + [reel("hit", plays=10_000, days=5)], NOW - timedelta(days=4))
            hist = load_history(path)
            now_reels = [reel("hit", plays=50_000, days=5)]                     # only today's hit is fetched; the rest come from history
            rows, _, base = outlier_feed(now_reels, hist, ["a"], k=3, now=NOW)
            self.assertEqual(base["a"], 1000.0)                                  # the five regulars come from history alone
            self.assertEqual([w.reel.id for w in rows], ["hit"])
            self.assertIsNone(rows[0].growth_per_day)                            # one earlier snapshot is not a trend yet
        hist2 = {"hit": [{"seen": (NOW - timedelta(days=4)).isoformat(), "plays": 10_000, "account": "a", "posted_at": None},
                         {"seen": NOW.isoformat(), "plays": 50_000, "account": "a", "posted_at": None}]}
        from scouts.watchlist import growth_per_day
        self.assertAlmostEqual(growth_per_day(hist2, reel("hit")), 10_000)
        same_day = {"hit": [{"seen": NOW.isoformat(), "plays": 1, "account": "a"}, {"seen": (NOW + timedelta(hours=2)).isoformat(), "plays": 9, "account": "a"}]}
        self.assertIsNone(growth_per_day(same_day, reel("hit")))


# ----------------------------------------------------------------------------- frameworks

FW_A = {"id": "a", "name": "A", "angles": ["story"], "beats": ["hook", "cta"], "match_any": ["x"], "shape": "s", "hook_formula": "h"}
FW_B = {"id": "b", "name": "B", "angles": ["proof"], "beats": ["hook", "cta"], "match_any": ["y"], "shape": "s", "hook_formula": "h"}
YES, NO = {"x": True, "y": False}, {"x": False, "y": False}


class FrameworkTests(unittest.TestCase):
    def board(self, viral, peers, pairs=(), library=None):
        return {e.fw["id"]: e for e in scoreboard([FW_A], library if library is not None else viral, viral, peers, list(pairs))}["a"]

    def test_unknown_is_not_use(self):
        self.assertFalse(uses(FW_A, {}))
        self.assertFalse(uses(FW_A, {"x": None}))
        self.assertTrue(uses(FW_A, {"x": True}))

    def test_supported_by_matched_comparison(self):
        e = self.board([YES] * 6, [NO] * 6)
        self.assertEqual(e.level, "supported")
        self.assertLess(e.q, 0.10)

    def test_common_to_both(self):
        e = self.board([YES] * 3 + [NO] * 3, [YES] * 3 + [NO] * 3)
        self.assertEqual(e.level, "common-to-both")

    def test_unused_by_anyone_is_thin_not_common(self):
        e = self.board([NO] * 5, [NO] * 5)
        self.assertEqual(e.level, "thin")

    def test_conflicting_evidence_is_mixed(self):
        e = self.board([NO] * 5, [YES] + [NO] * 4, pairs=[(YES, NO)] * 4, library=[YES] * 6 + [NO] * 6)
        self.assertEqual(e.level, "mixed")
        self.assertIn("disagrees", e.reasons[0])

    def test_supported_by_enough_pairs_and_not_by_too_few(self):
        self.assertEqual(self.board([], [], pairs=[(YES, NO)] * 6, library=[NO]).level, "supported")
        self.assertEqual(self.board([], [], pairs=[(YES, NO)] * 4, library=[NO]).level, "suggestive")

    def test_dropped_by_winners_is_not_favoured(self):
        self.assertEqual(self.board([], [], pairs=[(NO, YES)] * 4, library=[NO]).level, "not-favoured")

    def test_common_among_winners_without_comparison_is_only_suggestive(self):
        self.assertEqual(self.board([], [], library=[YES] * 5 + [NO] * 5).level, "suggestive")
        self.assertEqual(self.board([], [], library=[YES] * 3 + [NO] * 3).level, "thin")        # too few winners to say anything

    def test_pick_prefers_evidence_over_angle_fit(self):
        strong = Evidence(FW_A, level="suggestive")
        weak = Evidence(FW_B, level="thin")
        self.assertEqual(pick_framework([weak, strong], "proof", {}).fw["id"], "a")      # B suits the angle, A has the evidence

    def test_pick_uses_angle_as_tiebreak_cap_and_variety(self):
        a, b = Evidence(FW_A, level="suggestive"), Evidence(FW_B, level="suggestive")
        self.assertEqual(pick_framework([a, b], "proof", {}).fw["id"], "b")
        self.assertEqual(pick_framework([a, b], "proof", {"b": 2}, cap=2).fw["id"], "a")   # capped, so move on
        self.assertEqual(pick_framework([a], "proof", {"a": 5}, cap=2).fw["id"], "a")       # nothing else exists

    def test_experiment_slot_takes_an_untested_framework(self):
        strong, weak = Evidence(FW_A, level="supported"), Evidence(FW_B, level="thin")
        self.assertEqual(pick_framework([strong, weak], "story", {}, experiment=True).fw["id"], "b")
        self.assertEqual(pick_framework([strong], "story", {}, experiment=True).fw["id"], "a")   # none untested: fall back

    def test_avoided_levels_only_as_a_last_resort(self):
        bad, ok = Evidence(FW_A, level="common-to-both"), Evidence(FW_B, level="thin")
        self.assertEqual(pick_framework([bad, ok], "story", {}).fw["id"], "b")
        self.assertEqual(pick_framework([bad], "story", {}).fw["id"], "a")
        self.assertIsNone(pick_framework([], "story", {}))


# ----------------------------------------------------------------------------- script checks

CFG = {"words_per_second": 2.6, "target_seconds": 30, "audio_hook_max_words": 14, "text_hook_max_words": 8, "max_shared_words": 6, "max_rounds": 3}
FW = {"id": "f", "name": "F", "beats": ["hook", "point", "point", "cta"], "shape": "shape", "hook_formula": "h", "angles": ["story"]}
BRIEF = "Harshitha builds personal brands for founders. She has worked with 12 founders."


def words_of(n, seed="alpha"):
    return " ".join(f"{seed}{i}" for i in range(n))


def good(**over):
    spoken = [words_of(8, "h"), words_of(23, "p"), words_of(23, "q"), words_of(22, "c")]      # 76 words = ~29 seconds
    beats = [{"beat": b, "start_s": i * 7.0, "end_s": i * 7.0 + 7.0, "spoken": sp, "on_screen_text": "", "visual": "shot", "audio": ""}
             for i, (b, sp) in enumerate(zip(["hook", "point", "point", "cta"], spoken))]
    s = Script(title="t", hooks={"audio": "Stop posting more content now", "text": "Do this instead", "video": "Close-up to camera"},
               beats=beats, caption="cap", cta={"type": "dm", "text": "DM me the word brand"}, framework_id="f", topic="T", angle="story")
    for k, v in over.items():
        setattr(s, k, v)
    return s


def codes(s, refs=(), has_material=False, allowed=BRIEF):
    return {i.code for i in check_script(s, FW, CFG, allowed_text=allowed, reference_transcripts=list(refs), has_material=has_material) if i.severity == "error"}


class CheckTests(unittest.TestCase):
    def test_a_good_script_passes_everything(self):
        self.assertEqual(codes(good()), set())

    def test_runtime(self):
        s = good()
        s.beats[1]["spoken"] = words_of(80)
        self.assertIn("runtime", codes(s))
        s2 = good()
        for b in s2.beats:
            b["spoken"] = "short"
        self.assertIn("runtime", codes(s2))

    def test_three_hooks_and_lengths(self):
        self.assertIn("three_hooks", codes(good(hooks={"audio": "Hello there friend", "text": "", "video": "shot"})))
        self.assertIn("audio_hook_length", codes(good(hooks={"audio": words_of(20), "text": "t", "video": "v"})))
        self.assertIn("audio_hook_length", codes(good(hooks={"audio": "Hi", "text": "t", "video": "v"})))
        self.assertIn("text_hook_length", codes(good(hooks={"audio": "Stop posting more content", "text": words_of(12), "video": "v"})))

    def test_beat_order_and_framework_beats(self):
        s = good()
        s.beats[0]["beat"] = "setup"
        self.assertIn("beat_order", codes(s))
        s = good()
        s.beats[2]["beat"] = "proof"                      # only one 'point' where the framework needs two
        self.assertIn("framework_beats", codes(s))
        self.assertEqual(codes(Script()), {"no_beats"})

    def test_cta(self):
        self.assertIn("cta", codes(good(cta={"type": "dm", "text": ""})))

    def test_invented_numbers_are_caught_and_sourced_ones_are_not(self):
        s = good()
        s.beats[1]["spoken"] = "This grew revenue by 340% in 90 days " + words_of(15)
        self.assertIn("unsourced_number", codes(s))
        s.beats[1]["spoken"] = "I worked with 12 founders " + words_of(18)
        self.assertNotIn("unsourced_number", codes(s))                      # 12 is in the brief
        s.beats[1]["spoken"] = "Here are 3 ways " + words_of(18) + " [your real result, for example 40%]"
        self.assertNotIn("unsourced_number", codes(s))                      # a single digit is structure; placeholders are ignored
        s.caption = "Made a million doing this"
        self.assertIn("unsourced_number", codes(s))                         # number words count too

    def test_personal_claims_need_a_source(self):
        s = good()
        s.beats[1]["spoken"] = "My client doubled her audience. " + words_of(18)
        self.assertIn("personal_claim", codes(s, has_material=False))
        self.assertNotIn("personal_claim", codes(s, has_material=True))     # her own material may back it, shown as a warning
        warn = [i for i in check_script(s, FW, CFG, allowed_text=BRIEF, reference_transcripts=[], has_material=True) if i.code == "personal_claim"]
        self.assertEqual(warn[0].severity, "warn")
        s.beats[1]["spoken"] = "My client [what happened, in your words] doubled it. " + words_of(18)
        self.assertNotIn("personal_claim", codes(s, has_material=False))

    def test_copying_a_winner_is_caught(self):
        ref = "Everyone says personal branding is cringe. Honestly the cringe is the filter you must pass."
        s = good()
        s.beats[1]["spoken"] = "Honestly the cringe is the filter you must pass " + words_of(14)
        self.assertIn("copying", codes(s, refs=[ref]))
        s.beats[1]["spoken"] = "The cringe is just a filter " + words_of(17)      # shorter overlap than the limit
        self.assertNotIn("copying", codes(s, refs=[ref]))

    def test_all_check_codes_are_reachable(self):
        known = {c for c, _ in CHECKS}
        self.assertTrue({"runtime", "three_hooks", "unsourced_number", "personal_claim", "copying", "cta"} <= known)


class HelperTests(unittest.TestCase):
    def test_unsourced_numbers(self):
        self.assertEqual(unsourced_numbers("3 ways to grow", ""), [])
        self.assertEqual(unsourced_numbers("42% more", ""), ["42%"])
        self.assertEqual(unsourced_numbers("42% more", "we saw 42% last year"), [])
        self.assertEqual(unsourced_numbers("I made $1M", ""), ["$1M"])
        self.assertEqual(unsourced_numbers("[for example 40%]", ""), [])
        self.assertEqual(unsourced_numbers("a million views", ""), ["million"])
        self.assertEqual(unsourced_numbers("5x growth", ""), ["5x"])

    def test_shared_runs_and_subsequences(self):
        n, snippet = longest_shared_run(norm_words("so stop apologising for being visible today"), norm_words("Stop apologising for being visible."), 4)
        self.assertEqual((n, snippet), (5, "stop apologising for being visible"))
        self.assertEqual(longest_shared_run(norm_words("a b c"), norm_words("a b c"), 6), (0, ""))
        self.assertTrue(is_subsequence(["hook", "cta"], ["hook", "point", "cta"]))
        self.assertFalse(is_subsequence(["cta", "hook"], ["hook", "cta"]))

    def test_normalize_coerces_garbage(self):
        s = normalize_script({"beats": [{"beat": "weird", "start_s": "x", "spoken": 5}, "junk"], "hooks": None, "cta": "no", "hashtags": None}, VOCAB, "T", "story", "f")
        self.assertEqual(s.beats[0]["beat"], "point")
        self.assertIsNone(s.beats[0]["start_s"])
        self.assertEqual(s.beats[0]["spoken"], "5")
        self.assertEqual(s.hooks, {"audio": "", "text": "", "video": ""})
        self.assertEqual(normalize_script("not even a dict", VOCAB, "T", "a", "f").beats, [])
        self.assertEqual(normalize_script({"beats": "oops", "hook_variants": 5, "needs_from_you": {"a": 1}}, VOCAB, "T", "a", "f").hook_variants, [])


def raw_of(s: Script) -> dict:
    return {"title": s.title, "hooks": s.hooks, "hook_variants": [], "beats": s.beats, "caption": s.caption, "hashtags": [], "cta": s.cta,
            "needs_from_you": []}


class LoopTests(unittest.TestCase):
    CONTEXT = {"topic": "T", "angle": {"name": "story"}}

    def run_loop(self, llm, refs=(), has_material=False):
        return write_script(llm, self.CONTEXT, FW, VOCAB, CFG, allowed_text=BRIEF, reference_transcripts=list(refs), has_material=has_material)

    def test_problems_are_sent_back_and_fixed(self):
        bad = good()
        bad.beats[1]["spoken"] = "Revenue rose 340% overnight " + words_of(18)

        class Llm:
            def __init__(self): self.payloads = []
            def complete_json(self, system, user):
                self.payloads.append(json.loads(user))
                return raw_of(bad if "fix_these" not in self.payloads[-1] else good())
        llm = Llm()
        s = self.run_loop(llm)
        self.assertEqual((s.status, s.rounds), ("ready", 2))
        self.assertIn("340%", llm.payloads[1]["fix_these"][0])
        self.assertNotIn("fix_these", llm.payloads[0])

    def test_unfixable_script_is_marked_needs_work_not_ready(self):
        bad = good(cta={"type": "dm", "text": ""})

        class Llm:
            def complete_json(self, system, user): return raw_of(bad)
        s = self.run_loop(Llm())
        self.assertEqual((s.status, s.rounds), ("needs_work", 3))
        self.assertIn("cta", {i.code for i in s.issues})

    def test_model_failure_is_reported(self):
        class Llm:
            def complete_json(self, system, user): raise RuntimeError("api down")
        s = self.run_loop(Llm())
        self.assertEqual(s.status, "failed")
        self.assertIn("api down", s.error)

    def test_placeholders_become_a_to_do_list(self):
        g = good()
        g.beats[1]["spoken"] = "Here is what happened [your real story about a client] " + words_of(15)
        g.beats[1]["visual"] = "[a photo of your desk]"

        class Llm:
            def complete_json(self, system, user): return raw_of(g)
        s = self.run_loop(Llm())
        self.assertIn("[your real story about a client]", s.needs_from_you)
        self.assertIn("[a photo of your desk]", s.needs_from_you)

    def test_the_prompt_forbids_inventing_and_copying(self):
        for phrase in ("Never invent a statistic", "NOT given their words", "fix_these"):
            self.assertIn(phrase, SCRIPT_SYSTEM)


# ----------------------------------------------------------------------------- script_run

class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.lib = [reel(f"w{i}", account=f"acc{i}", plays=900_000, topic="T", heat=90 - i, transcript=f"UNIQUEWORDS{i} secret winning sentence here that nobody else says") for i in range(4)]
        from scouts.viral_analysis import normalize_breakdown
        raw = {"hooks": {"audio": {"text": "SECRETHOOKTEXT", "type": "contrarian"}, "text": {"text": "", "type": "none"}, "video": {"description": "", "type": "none"}},
               "loop": {"type": "myth-bust"}, "spice": ["controversy"], "cta": {"type": "dm"}, "structure": [{"beat": "hook", "summary": "SECRETSUMMARY"}], "format": "talking-head"}
        self.bds = {r.id: normalize_breakdown(raw, r, VOCAB, 0) for r in self.lib}
        self.feats = {r.id: {"loop:myth-bust": True} for r in self.lib}
        idea = lambda a: SimpleNamespace(angle=a, pitch="a pitch", hook="a hook")
        self.picks = [SimpleNamespace(topic=SimpleNamespace(name="T"), angles=[idea("contrarian")], slot=s) for s in ("data", "data", "experiment", "data")]
        self.board = [Evidence(dict(FW, id="m", name="M", beats=["hook", "point", "point", "cta"], angles=["contrarian"], match_any=["loop:myth-bust"]), level="suggestive", reasons=["r"]),
                      Evidence(dict(FW, id="n", name="N", angles=["story"], match_any=["z"]), level="thin", reasons=["t"])]

    def run_it(self, llm, slots=None, **cfg):
        if slots:
            idea = lambda a: SimpleNamespace(angle=a, pitch="a pitch", hook="a hook")
            self.picks = [SimpleNamespace(topic=SimpleNamespace(name="T"), angles=[idea("contrarian")], slot=sl) for sl in slots]
        c = {**CFG, "count": 5, "max_per_framework": 2, **cfg}
        return generate_scripts(self.picks, self.board, self.lib, self.bds, self.feats, {"contrarian": "meaning"}, llm, VOCAB, BRIEF, "", c)

    def test_the_writer_never_sees_a_winners_words(self):
        sent = []
        class Llm:
            def complete_json(self, system, user):
                sent.append(user)
                return raw_of(good())
        self.run_it(Llm())
        blob = " ".join(sent)
        for secret in ("UNIQUEWORDS0", "secret winning sentence", "SECRETHOOKTEXT", "SECRETSUMMARY"):
            self.assertNotIn(secret, blob)
        self.assertIn("audio_hook_type", blob)
        self.assertIn("suggestive", blob)                                    # the framework's evidence level is passed along

    def test_copying_is_checked_against_every_winner(self):
        copied = good()
        copied.beats[1]["spoken"] = "UNIQUEWORDS2 secret winning sentence here that nobody " + words_of(16)
        class Llm:
            def complete_json(self, system, user): return raw_of(copied)
        res = self.run_it(Llm())
        self.assertTrue(all("copying" in {i.code for i in r.script.issues} for r in res))
        self.assertTrue(all(r.script.status == "needs_work" for r in res))

    def test_count_limit_and_the_weekly_variety_cap(self):
        class Llm:
            def complete_json(self, system, user): return raw_of(good())
        res = self.run_it(Llm(), slots=["data"] * 4, count=3)
        self.assertEqual(len(res), 3)
        self.assertEqual([r.evidence.fw["id"] for r in res], ["m", "m", "n"])       # m is capped at two uses, so the third moves on

    def test_the_experiment_slot_takes_an_untested_framework_even_when_the_cap_is_not_hit(self):
        class Llm:
            def complete_json(self, system, user): return raw_of(good())
        res = self.run_it(Llm(), slots=["data", "experiment"], max_per_framework=5)
        self.assertEqual([r.evidence.fw["id"] for r in res], ["m", "n"])            # only the experiment logic can explain this
        self.assertEqual([r.slot for r in res], ["data", "experiment"])
        res = self.run_it(Llm(), slots=["data", "data"], max_per_framework=5)
        self.assertEqual([r.evidence.fw["id"] for r in res], ["m", "m"])

    def test_no_framework_means_no_scripts_not_a_crash(self):
        self.board = []
        class Llm:
            def complete_json(self, system, user): raise AssertionError("should not be called")
        self.assertEqual(self.run_it(Llm()), [])

    def test_reference_helpers(self):
        refs = choose_references(self.board[0].fw, self.lib, self.feats, "T", k=2)
        self.assertEqual([r.id for r in refs], ["w0", "w1"])
        brief = reference_brief(self.bds["w0"])
        self.assertEqual(brief["audio_hook_type"], "contrarian")
        self.assertNotIn("SECRETHOOKTEXT", json.dumps(brief))


# ----------------------------------------------------------------------------- end to end

class EndToEnd(unittest.TestCase):
    def test_sample_run_writes_scripts_frameworks_and_watchlist(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(StringIO()):
            self.assertEqual(run_weekly.main(["--sample", "--out", d]), 0)
            out = Path(d)
            files = sorted((out / "scripts").glob("*.md"))
            self.assertGreaterEqual(len(files), 1)
            text = files[0].read_text()
            for must in ("SAMPLE RUN", "The first 3 seconds", "Shot by shot", "## Checks", "Built from (structure only)"):
                self.assertIn(must, text)
            data = json.loads((out / "scripts.json").read_text())
            self.assertTrue(all(s["status"] in ("ready", "needs_work", "failed") for s in data))
            self.assertTrue(any(s["framework_evidence"]["level"] for s in data))
            self.assertIn("**supported**", (out / "frameworks.md").read_text())
            self.assertTrue((out / "watchlist.md").exists())
            slots = [("experiment" in f.read_text().split("**Slot:**")[1][:15]) for f in files]
            self.assertLessEqual(sum(slots), 1)


if __name__ == "__main__":
    unittest.main()
