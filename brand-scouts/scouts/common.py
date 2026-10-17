"""Shared types and helpers. Standard library only."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value) -> Optional[datetime]:
    """Accepts datetime, ISO string, or epoch seconds/milliseconds. Returns aware UTC or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else value
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Reel:
    id: str
    url: str
    account: str
    caption: str = ""
    transcript: str = ""
    followers: Optional[int] = None
    plays: int = 0
    likes: int = 0
    comments: int = 0
    posted_at: Optional[datetime] = None
    source: str = ""
    account_median_plays: Optional[float] = None
    video_url: str = ""            # direct video file, for frame extraction (Apify links can expire)
    duration_s: Optional[float] = None
    # derived by triage
    velocity: float = 0.0        # plays per day since posting
    reach_ratio: float = 0.0     # plays / max(followers, 1000)
    outperformance: float = 0.0  # plays / account median, or reach_ratio when the median is unknown
    comment_ratio: float = 0.0   # comments / likes
    heat: float = 0.0            # 0-100, percentile blend of velocity and outperformance
    # filled by labelling
    topic: str = ""
    angle: str = ""
    cta_type: str = ""
    hook: str = ""

    @property
    def text(self) -> str:
        return f"{self.caption}\n{self.transcript}".strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Reel":
        kw = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        kw["posted_at"] = parse_datetime(kw.get("posted_at"))
        return cls(**kw)


def percentile_ranks(values: list[float]) -> list[float]:
    """Rank each value 0-100 within the list. Ties share their average rank. One value -> 50."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = 100.0 * avg / (n - 1)
        i = j + 1
    return ranks


def read_lines(path: Path) -> list[str]:
    """Non-empty lines, skipping # comments."""
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("//") and not (line.startswith("#") and not line.startswith("#!") and line[1:2] in (" ", "")):
            lines.append(line)
    return lines


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader. Existing environment variables win."""
    if not Path(path).exists():
        return
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
