import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import web
from scouts import workbook
from scouts.common import utcnow
from scouts.fake_llm import FakeLLM

NOW = utcnow()


class Scripted:
    """Stand-in model that returns a fixed reply per task tag."""
    def __init__(self, **by_tag):
        self.by_tag = by_tag

    def complete_json(self, system, user, images=None):
        for tag, reply in self.by_tag.items():
            if f"[TASK:{tag}]" in system:
                return reply(json.loads(user)) if callable(reply) else reply
        raise ValueError("unexpected task")


class Pieces(unittest.TestCase):
    PAIRS = [("r1", "I struggle with this every single day"), ("r1", "where can I buy this one please"), ("r2", "is it better than the other brand honestly"),
             ("r2", "wow"), ("r3", "how do I pick which one is right for me")]

    def test_awareness_counts_are_computed_here_and_examples_are_verbatim(self):
        aw = workbook.awareness_map(FakeLLM(), self.PAIRS, "B", "C")
        self.assertEqual(aw["comments"], 5)
        self.assertEqual(aw["placed"], 4)                        # 'wow' is too short to sort
        self.assertAlmostEqual(sum(s["share"] for s in aw["stages"]), 1.0, places=2)
        said = {c for _, c in self.PAIRS}
        for s in aw["stages"]:
            for ex in s["examples"]:
                self.assertIn(ex["text"], said)

    def test_model_cannot_invent_stages_or_indexes(self):
        llm = Scripted(awareness={"labels": [{"i": 0, "stage": 9}, {"i": 99, "stage": 2}, {"i": 1, "stage": 4}, {"i": 2, "stage": "x"}]})
        aw = workbook.awareness_map(llm, self.PAIRS, "B", "C")
        self.assertEqual(aw["placed"], 1)
        self.assertEqual(aw["stages"][4]["count"], 1)

    def test_avatar_needs_enough_real_comments_and_quotes_a_stored_comment(self):
        aw = {"stages": [{"stage": 0, "name": "Problem unaware", "count": 2, "share": .2, "examples": [{"text": "a b c", "reel_id": "x"}]},
                         {"stage": 1, "name": "Problem aware", "count": 5, "share": .5, "examples": [{"text": f"comment number {i}", "reel_id": "x"} for i in range(5)]}]}
        llm = Scripted(avatar={"name": "Tired Tara", "problem": "p", "belief": "b", "objection": "o", "formats": ["f1", "f2", "f3"], "quote": 3})
        out = workbook.avatars(llm, aw, "B", "C")
        self.assertEqual(len(out["avatars"]), 1)
        self.assertEqual(out["avatars"][0]["words"], "comment number 3")
        self.assertEqual(out["avatars"][0]["formats"], ["f1", "f2"])
        self.assertTrue(out["skipped"])
        bad = workbook.avatars(Scripted(avatar={"name": "x", "quote": 99}), aw, "B", "C")["avatars"][0]
        self.assertEqual(bad["words"], "comment number 0")        # an out-of-range pick falls back, never invents

    def test_ideas_drop_copied_hooks_and_unknown_sources(self):
        card = {"link": "https://www.instagram.com/reel/a/", "creator": "a", "tier": "micro", "content_angle": "List / how-to", "format": "talking head", "structure": ["hook"],
                "hook": {"audio": {"text": "three mistakes everyone makes with serums"}, "text": {"text": ""}}}
        llm = Scripted(ideation={"ideas": [
            {"hook": "Three mistakes everyone makes with serums", "source": 1, "goal": "Sales"},      # copies the source wording
            {"hook": "What I wish I knew before my first order", "source": 7},                       # no such reference
            {"hook": "What I wish I knew before my first order", "source": 1, "goal": "bogus", "avatar": "ghost"}]})
        out = workbook.ideation(llm, {"brand": "B"}, [card], {"avatars": [{"name": "Tara", "problem": "", "objection": ""}]})
        self.assertEqual(len(out["ideas"]), 1)
        self.assertEqual((out["ideas"][0]["goal"], out["ideas"][0]["avatar"], out["dropped"]), ("Awareness", "", 2))

    def test_storyboard_flags_numbers_that_are_not_the_users(self):
        llm = Scripted(storyboard={"shots": [{"line": "Over 4,000 customers saw 37% better skin", "shot_type": "weird", "angle": "Eye level"}, {"line": "Two weeks in"}]})
        out = workbook.storyboard(llm, {"hook": "x", "proof": "my 2 weeks of photos"}, {"brand": "B"}, None, "")
        self.assertEqual(out["shots"][0]["shot_type"], "Medium shot")                 # invalid choice is replaced
        self.assertIn("4,000", out["flagged_numbers"])
        self.assertIn("37", out["flagged_numbers"][1] if len(out["flagged_numbers"]) > 1 else "37")
        self.assertNotIn("2", out["flagged_numbers"])                                  # that number is in the user's own idea
        self.assertTrue(any("Check these numbers" in n for n in out["needs_from_you"]))

    def test_site_facts_survive_only_with_a_real_quote(self):
        page = {"url": "https://x.example", "title": "", "text": "Barrier Serum with niacinamide. Only Rs 499 for 30 ml. Gentle on dry skin."}
        llm = Scripted(site={"positioning": {"value": "Gentle skincare", "evidence": "Gentle on dry skin"},
                             "price": {"value": "Rs 999", "evidence": "Only Rs 999 for 30 ml"},                    # evidence not on the page
                             "claims": [{"value": "Contains niacinamide", "evidence": "with niacinamide"}, {"value": "Clinically proven", "evidence": "Clinically proven"}]})
        p = workbook.site_profile(llm, page, "X")
        self.assertEqual(p["positioning"], "Gentle skincare")
        self.assertEqual(p["price"], "")
        self.assertEqual(p["claims"], ["Contains niacinamide"])

    def test_private_addresses_are_never_fetched(self):
        for bad in ("http://127.0.0.1/", "http://localhost:8000/x", "http://10.0.0.5", "http://169.254.169.254/latest", "ftp://example.com", "https://user:pw@example.com", ""):
            with self.assertRaises(ValueError, msg=bad):
                workbook.public_url(bad)

    def test_excel_cells_cannot_become_formulas(self):
        self.assertEqual(workbook._cell("=HYPERLINK(\"http://evil\")"), "'=HYPERLINK(\"http://evil\")")
        self.assertEqual(workbook._cell(None), "")


class Flow(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        app = web.App(self.dir / "v.db", True, now=NOW)
        srv = web.serve(app, 0)
        self.port = srv.server_address[1]
        srv.RequestHandlerClass = web.make_handler(app, self.port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

    def call(self, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers

    def wait(self, jid, until):
        for _ in range(150):
            j = self.call("/api/job/" + jid)[1]
            if j["status"] in until or j["status"] == "error":
                return j
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_sample_workbook_end_to_end(self):
        body = {"brand": "Dewy Day", "category": "skincare", "days": 30, "watch": "@one, two", "competitor_sites": "Rival | https://rival.example",
                "website": "https://dewy.example"}
        self.assertEqual(self.call("/api/wb/plan", body)[1]["sample"], True)
        jid = self.call("/api/wb/start", body)[1]["job"]
        j = self.wait(jid, {"gate"})
        self.assertEqual((j["status"], j["error"]), ("gate", ""))
        wb = self.call("/api/wb?id=" + j["wb_id"])[1]
        self.assertTrue(wb["research"]["cards"] and wb["ideas"] and wb["avatars"]["avatars"])
        self.assertEqual(wb["scripts"], [])                                           # nothing is scripted before approval
        self.assertEqual(wb["sites"]["brand"]["who"], "Dewy Day")
        self.assertEqual(self.call("/api/wb/approve", {"id": wb["id"], "approved": [99]})[0], 400)
        jid = self.call("/api/wb/approve", {"id": wb["id"], "approved": [0, 1]})[1]["job"]
        j = self.wait(jid, {"done"})
        self.assertEqual((j["status"], j["error"]), ("done", ""))
        wb = self.call("/api/wb?id=" + wb["id"])[1]
        self.assertEqual([s["id"] for s in wb["scripts"]], ["S-01", "S-02"])
        self.assertTrue(all(s["shots"] for s in wb["scripts"]))
        self.assertEqual(self.call("/api/state")[1]["workbooks"][0]["scripts"], 2)
        code, data, headers = self.call("/api/wb/export?id=" + wb["id"])
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertTrue(any(n.startswith("xl/worksheets/sheet9") for n in names))      # nine sheets
        code, page, headers = self.call("/")
        self.assertIn(b"bioscriptz.js", page)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertIn(b"Outlier", self.call("/classic")[1])

    def test_rejects_bad_workbook_input(self):
        self.assertEqual(self.call("/api/wb/start", {"brand": "", "category": "x"})[0], 400)
        self.assertEqual(self.call("/api/wb/start", {"brand": "B", "category": "c", "watch": "bad handle!"})[0], 400)
        self.assertEqual(self.call("/api/wb/start", {"brand": "B", "category": "c", "days": 5})[0], 400)
        self.assertEqual(self.call("/api/wb?id=nope")[0], 404)
        self.assertEqual(self.call("/api/wb/export?id=nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
