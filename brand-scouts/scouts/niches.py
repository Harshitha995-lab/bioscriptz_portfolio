"""Step 1: the niche watchlist. A niche is a name, the keywords/hashtags that find its content, and the creators to watch."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import ROOT

HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
DEFAULT_PATH = ROOT / "config" / "niches.json"


def clean_handle(h: str) -> str:
    return h.strip().lstrip("@").lower()


def clean_keyword(k: str) -> str:
    return " ".join(k.strip().split())


@dataclass
class Niche:
    name: str
    keywords: list = field(default_factory=list)   # "#hashtag" or plain search terms
    creators: list = field(default_factory=list)   # Instagram handles, no @


class Niches:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.items: list[Niche] = []
        if self.path.exists():
            for n in json.loads(self.path.read_text(encoding="utf-8")).get("niches", []):
                self.items.append(Niche(n["name"], list(n.get("keywords", [])), list(n.get("creators", []))))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"niches": [{"name": n.name, "keywords": n.keywords, "creators": n.creators} for n in self.items]}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def get(self, name: str) -> Niche | None:
        return next((n for n in self.items if n.name.lower() == name.strip().lower()), None)

    def require(self, name: str) -> Niche:
        n = self.get(name)
        if n is None:
            raise ValueError(f"No niche called '{name}'. Existing: {', '.join(x.name for x in self.items) or 'none'}")
        return n

    def add_niche(self, name: str) -> Niche:
        name = " ".join(name.split())
        if not name:
            raise ValueError("A niche needs a name.")
        if self.get(name):
            raise ValueError(f"Niche '{name}' already exists.")
        n = Niche(name)
        self.items.append(n)
        return n

    def remove_niche(self, name: str) -> None:
        self.items.remove(self.require(name))

    def add_keywords(self, name: str, kws: list[str]) -> tuple[int, list[str]]:
        n, added, problems = self.require(name), 0, []
        for k in map(clean_keyword, kws):
            if not k or k == "#":
                continue
            if len(k) > 80:
                problems.append(f"'{k[:20]}…' is longer than 80 characters")
            elif k.lower() in (x.lower() for x in n.keywords):
                continue
            else:
                n.keywords.append(k)
                added += 1
        return added, problems

    def add_creators(self, name: str, handles: list[str]) -> tuple[int, list[str]]:
        n, added, problems = self.require(name), 0, []
        for h in map(clean_handle, handles):
            if not h:
                continue
            if not HANDLE.match(h):
                problems.append(f"'{h}' is not a valid Instagram handle")
            elif h not in n.creators:
                n.creators.append(h)
                added += 1
        return added, problems

    def remove_keyword(self, name: str, kw: str) -> bool:
        n = self.require(name)
        kept = [k for k in n.keywords if k.lower() != clean_keyword(kw).lower()]
        changed = len(kept) != len(n.keywords)
        n.keywords = kept
        return changed

    def remove_creator(self, name: str, handle: str) -> bool:
        n = self.require(name)
        kept = [c for c in n.creators if c != clean_handle(handle)]
        changed = len(kept) != len(n.creators)
        n.creators = kept
        return changed

    def selected(self, name: str | None) -> list[Niche]:
        return [self.require(name)] if name else list(self.items)

    def keyword_lines(self, name: str | None = None) -> list[str]:
        seen, out = set(), []
        for n in self.selected(name):
            for k in n.keywords:
                if k.lower() not in seen:
                    seen.add(k.lower())
                    out.append(k)
        return out

    def creators(self, name: str | None = None) -> list[str]:
        seen, out = set(), []
        for n in self.selected(name):
            for c in n.creators:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out

    def keyword_map(self) -> dict[str, str]:
        """keyword (lowercase, no #) -> niche. If two niches share a keyword, the first one listed wins."""
        out: dict[str, str] = {}
        for n in self.items:
            for k in n.keywords:
                out.setdefault(k.lower().lstrip("#"), n.name)
        return out

    def creator_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for n in self.items:
            for c in n.creators:
                out.setdefault(c, n.name)
        return out
