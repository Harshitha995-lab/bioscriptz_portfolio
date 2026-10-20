"""The content vault: one local SQLite file for everything the agent collects and makes.

Why it exists: on Apify's free plan every scraped result costs credit. Scrape once, keep it here, and every later step
(outliers, transcripts, breakdowns, scripts) reads from the vault for free. It also holds the scripts, with status and tags,
and a ledger of what each paid run cost.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .common import ROOT, Reel, parse_datetime, utcnow
from .viral_analysis import ViralBreakdown

DEFAULT_PATH = ROOT / "data" / "vault.db"
STATUSES = ("idea", "drafted", "filmed", "posted", "archived")
TAG = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,29}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
  id TEXT PRIMARY KEY, account TEXT, url TEXT, caption TEXT, transcript TEXT, followers INTEGER,
  plays INTEGER, likes INTEGER, comments INTEGER, posted_at TEXT, keyword TEXT, niche TEXT, source TEXT,
  video_url TEXT, duration_s REAL, first_seen TEXT, last_seen TEXT);
CREATE INDEX IF NOT EXISTS reels_account ON reels(account);
CREATE INDEX IF NOT EXISTS reels_niche ON reels(niche);
CREATE TABLE IF NOT EXISTS snapshots (id TEXT, seen TEXT, plays INTEGER, likes INTEGER, comments INTEGER);
CREATE INDEX IF NOT EXISTS snapshots_id ON snapshots(id);
CREATE TABLE IF NOT EXISTS breakdowns (reel_id TEXT PRIMARY KEY, data TEXT, analysed_at TEXT);
CREATE TABLE IF NOT EXISTS scripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, title TEXT, niche TEXT, topic TEXT, angle TEXT, framework_id TEXT,
  framework_level TEXT, quality TEXT, status TEXT, source_reel_id TEXT, tags TEXT DEFAULT '', notes TEXT DEFAULT '', data TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, cost_usd REAL, results INTEGER, note TEXT);
"""


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def clean_tags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = " ".join(t.lower().split())
        if not TAG.match(t):
            raise ValueError(f"'{t}' is not a valid tag (letters, numbers, spaces, - and _, up to 30 characters)")
        if t not in out:
            out.append(t)
    return out


class Vault:
    def __init__(self, path=DEFAULT_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self.db.close()

    # ---------------------------------------------------------------- reels
    def upsert_reels(self, reels: list[Reel], now: datetime | None = None) -> tuple[int, int]:
        """Insert new Reels, refresh numbers on known ones. A transcript or niche we already have is never blanked out."""
        now_s = (now or utcnow()).isoformat()
        new = updated = 0
        with self.db:
            for r in reels:
                exists = self.db.execute("SELECT 1 FROM reels WHERE id = ?", (r.id,)).fetchone()
                self.db.execute(
                    """INSERT INTO reels (id, account, url, caption, transcript, followers, plays, likes, comments, posted_at, keyword,
                                          niche, source, video_url, duration_s, first_seen, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         plays=excluded.plays, likes=excluded.likes, comments=excluded.comments, followers=COALESCE(excluded.followers, followers),
                         last_seen=excluded.last_seen,
                         caption=CASE WHEN excluded.caption != '' THEN excluded.caption ELSE caption END,
                         transcript=CASE WHEN excluded.transcript != '' THEN excluded.transcript ELSE transcript END,
                         niche=CASE WHEN excluded.niche != '' THEN excluded.niche ELSE niche END,
                         keyword=CASE WHEN excluded.keyword != '' THEN excluded.keyword ELSE keyword END,
                         video_url=CASE WHEN excluded.video_url != '' THEN excluded.video_url ELSE video_url END,
                         duration_s=COALESCE(excluded.duration_s, duration_s)""",
                    (r.id, r.account, r.url, r.caption, r.transcript, r.followers, r.plays, r.likes, r.comments,
                     r.posted_at.isoformat() if r.posted_at else None, r.keyword, r.niche, r.source, r.video_url, r.duration_s, now_s, now_s))
                self.db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (r.id, now_s, r.plays, r.likes, r.comments))
                new, updated = new + (not exists), updated + bool(exists)
        return new, updated

    @staticmethod
    def _reel(row: sqlite3.Row) -> Reel:
        return Reel(id=row["id"], url=row["url"] or "", account=row["account"] or "unknown", caption=row["caption"] or "",
                    transcript=row["transcript"] or "", followers=row["followers"], plays=row["plays"] or 0, likes=row["likes"] or 0,
                    comments=row["comments"] or 0, posted_at=parse_datetime(row["posted_at"]), source=row["source"] or "",
                    keyword=row["keyword"] or "", niche=row["niche"] or "", video_url=row["video_url"] or "", duration_s=row["duration_s"])

    def reels(self, niche: str | None = None) -> list[Reel]:
        sql, args = "SELECT * FROM reels", ()
        if niche:
            sql, args = sql + " WHERE lower(niche) = lower(?)", (niche,)
        return [self._reel(r) for r in self.db.execute(sql, args)]

    def get_reel(self, reel_id: str) -> Reel | None:
        row = self.db.execute("SELECT * FROM reels WHERE id = ?", (reel_id,)).fetchone()
        return self._reel(row) if row else None

    def set_transcript(self, reel_id: str, text: str) -> None:
        with self.db:
            self.db.execute("UPDATE reels SET transcript = ? WHERE id = ?", (text, reel_id))

    def snapshots(self, reel_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM snapshots WHERE id = ? ORDER BY seen", (reel_id,))]

    def count(self, table: str) -> int:
        if table not in ("reels", "snapshots", "breakdowns", "scripts", "runs"):
            raise ValueError("unknown table")
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    # ---------------------------------------------------------------- breakdowns
    def save_breakdown(self, bd: ViralBreakdown) -> None:
        if bd.error:
            return                                  # never cache a failure: it should be retried
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO breakdowns VALUES (?,?,?)", (bd.reel_id, json.dumps(bd.to_dict()), utcnow().isoformat()))

    def breakdowns(self, ids: list[str] | None = None) -> dict[str, ViralBreakdown]:
        rows = self.db.execute("SELECT reel_id, data FROM breakdowns").fetchall()
        wanted = set(ids) if ids is not None else None
        return {r["reel_id"]: ViralBreakdown(**json.loads(r["data"])) for r in rows if wanted is None or r["reel_id"] in wanted}

    # ---------------------------------------------------------------- scripts
    def add_script(self, script_dict: dict, *, niche: str = "", source_reel_id: str = "", framework_level: str = "",
                   status: str = "drafted", tags: list[str] | None = None, extra: dict | None = None) -> int:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        tag_s = "," + ",".join(clean_tags(tags or [])) + "," if tags else ""
        data = {**script_dict, **(extra or {})}
        with self.db:
            cur = self.db.execute(
                "INSERT INTO scripts (created_at, title, niche, topic, angle, framework_id, framework_level, quality, status, source_reel_id, tags, data) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (utcnow().isoformat(), script_dict.get("title", ""), niche, script_dict.get("topic", ""), script_dict.get("angle", ""),
                 script_dict.get("framework_id", ""), framework_level, script_dict.get("status", ""), status, source_reel_id, tag_s,
                 json.dumps(data, default=str)))
        return cur.lastrowid

    @staticmethod
    def _script(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["tags"] = [t for t in d["tags"].split(",") if t]
        d["data"] = json.loads(d["data"])
        return d

    def scripts(self, *, status: str | None = None, niche: str | None = None, tag: str | None = None, search: str | None = None) -> list[dict]:
        where, args = [], []
        if status:
            where.append("status = ?"); args.append(status)
        if niche:
            where.append("lower(niche) = lower(?)"); args.append(niche)
        if tag:
            where.append("tags LIKE ? ESCAPE '\\'"); args.append(_like("," + tag.lower() + ","))
        if search:
            where.append("(title LIKE ? ESCAPE '\\' OR topic LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR data LIKE ? ESCAPE '\\')")
            args += [_like(search)] * 5
        sql = "SELECT * FROM scripts" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC"
        return [self._script(r) for r in self.db.execute(sql, args)]

    def get_script(self, script_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        return self._script(row) if row else None

    def update_script(self, script_id: int, *, status: str | None = None, add_tags: list[str] | None = None,
                      remove_tags: list[str] | None = None, notes: str | None = None) -> dict:
        cur = self.get_script(script_id)
        if cur is None:
            raise ValueError(f"No script with id {script_id}")
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        tags = [t for t in cur["tags"] if t not in clean_tags(remove_tags or [])]
        tags += [t for t in clean_tags(add_tags or []) if t not in tags]
        with self.db:
            self.db.execute("UPDATE scripts SET status = ?, tags = ?, notes = ? WHERE id = ?",
                            (status or cur["status"], ("," + ",".join(tags) + ",") if tags else "", cur["notes"] if notes is None else notes, script_id))
        return self.get_script(script_id)

    def delete_script(self, script_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM scripts WHERE id = ?", (script_id,)).rowcount > 0

    # ---------------------------------------------------------------- small key/value store (for example the latest framework ratings)
    def set_meta(self, key: str, value) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, default=str)))

    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    # ---------------------------------------------------------------- spend ledger
    def record_run(self, kind: str, cost_usd: float, results: int, note: str = "", when: datetime | None = None) -> None:
        with self.db:
            self.db.execute("INSERT INTO runs (ts, kind, cost_usd, results, note) VALUES (?,?,?,?,?)",
                            ((when or utcnow()).isoformat(), kind, float(cost_usd), int(results), note))

    def month_spend(self, when: datetime | None = None) -> float:
        prefix = (when or utcnow()).strftime("%Y-%m")
        row = self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE ts LIKE ?", (prefix + "%",)).fetchone()
        return float(row[0])

    def runs(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY id DESC")]
