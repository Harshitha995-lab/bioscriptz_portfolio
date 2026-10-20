#!/usr/bin/env python3
"""Checks that this computer is ready for a live run. Prints what to fix. Makes no network calls and never prints your keys."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys

from scouts.common import ROOT, load_env


def main() -> int:
    load_env()
    problems = 0

    def row(ok: bool, what: str, fix: str = "", needed: bool = True) -> None:
        nonlocal problems
        print(f"  [{'ok' if ok else ('FIX' if needed else 'optional')}] {what}" + ("" if ok or not fix else f"\n        -> {fix}"))
        problems += (not ok) and needed

    print("Python and tools")
    row(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (needs 3.10 or newer)", "Install Python 3.11+ from python.org and tick 'Add to PATH'")
    row(shutil.which("ffmpeg") is not None, "ffmpeg (video frames and audio for transcripts)",
        "In PowerShell: winget install Gyan.FFmpeg   then close and reopen the terminal")
    from scouts.llm import key_name, provider
    try:
        which = provider()
    except ValueError as exc:
        which = "anthropic"
        row(False, str(exc), "Set LLM_PROVIDER=anthropic or LLM_PROVIDER=gemini in .env")
    for mod, pipname, needed in (("apify_client", "apify-client", True), ("anthropic", "anthropic", which == "anthropic"),
                                 ("google.genai", "google-genai", which == "gemini"), ("faster_whisper", "faster-whisper", True),
                                 ("openpyxl", "openpyxl", False)):
        try:
            found = importlib.util.find_spec(mod) is not None
        except ModuleNotFoundError:          # a dotted name whose parent package is missing
            found = False
        row(found, f"Python package {pipname}", f"pip install {pipname}", needed)

    print("Keys in .env (values are never shown)")
    print(f"  AI provider: {which}")
    for k in ("APIFY_TOKEN", key_name(which)):
        row(bool(os.environ.get(k)), k, f"Add a line {k}=... to {ROOT / '.env'}")

    print("config/apify.json")
    cfg = json.loads((ROOT / "config" / "apify.json").read_text(encoding="utf-8"))
    row(cfg.get("actor_id", "REPLACE_ME") != "REPLACE_ME", f"actor: {cfg.get('actor_id')}")
    row(cfg.get("price_per_1000_results_usd") is not None, f"price per 1,000 results: {cfg.get('price_per_1000_results_usd')}")
    row(bool(cfg.get("input_verified")), "keyword search verified")
    row(cfg.get("profile_verified") is True, "creator baselines verified", needed=False)

    print()
    print("Ready for a live run." if not problems else f"{problems} thing(s) to fix before a live run.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
