"""Production-ready Reel scripts from an evidence-rated framework.

The model drafts; code checks. A script is only called ready if it passes every error-level check, and anything
the checks catch is sent back to the model to fix (a few rounds). What the checks guard against:
  - invented statistics or results      -> numbers must come from the brand brief or Harshitha's own material
  - invented client stories             -> personal claims must be sourced or left as [placeholders]
  - lifting a winner's words            -> no run of N words may match a reference transcript
  - a script that cannot be filmed      -> runtime, hook length, three hooks, framework beats, CTA
The model is shown how winners were built (hook type, loop, beats), never their wording.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .llm import LLM

SCRIPT_SYSTEM = (
    "[TASK:script]\n"
    "You write one production-ready short-form video script (Instagram Reel) for the founder of a personal-branding agency, "
    "in her voice, using the storytelling framework and angle supplied.\n"
    "Hard rules:\n"
    "- Never invent a statistic, number, client, result, quote or personal story. Use only facts in `brand_brief` or `my_material`. "
    "Where a real example is needed, write a [bracketed placeholder] describing exactly what she must supply.\n"
    "- `references` describe how winning Reels were built (hook type, loop, beats). You are NOT given their words; do not try to "
    "imitate any wording. Use the structure, not the sentences.\n"
    "- Provide all three hooks: audio (the first spoken line, short enough to say in about 3 seconds), text (on-screen words in the "
    "first 3 seconds, short), and video (what the viewer sees in the first 3 seconds, filmable with a phone).\n"
    "- Follow the framework's beats in order. Spoken lines must fit `target_seconds` at `words_per_second`.\n"
    "- If `fix_these` is present, your previous draft failed those checks: fix every one of them.\n"
    'Return {"title": ..., "hooks": {"audio": ..., "text": ..., "video": ...}, "hook_variants": [{"audio": ..., "text": ..., "video": ..., "why": ...}], '
    '"beats": [{"beat": ..., "start_s": ..., "end_s": ..., "spoken": ..., "on_screen_text": ..., "visual": ..., "audio": ...}], '
    '"caption": ..., "hashtags": [...], "cta": {"type": ..., "text": ...}, "needs_from_you": [...]}.'
)

CHECKS = [("runtime", "Spoken length fits the target runtime"), ("three_hooks", "Has an audio, an on-screen text and a video hook"),
          ("audio_hook_length", "Audio hook fits the first 3 seconds"), ("text_hook_length", "On-screen text hook is short"),
          ("beat_order", "Starts with the hook and ends with the CTA"), ("framework_beats", "Follows the framework's beats in order"),
          ("cta", "Has a call to action"), ("unsourced_number", "No statistic or figure that is not in your brief or material"),
          ("personal_claim", "No client story or personal result without a source"), ("copying", "Shares no run of words with any winning Reel")]

PERSONAL_CLAIM = re.compile(
    r"\b(my (?:client|clients|customer|customers|team|company|startup|agency|students|business)|"
    r"(?:i|we) (?:helped|grew|built|made|launched|sold|signed|got|hit|reached|doubled|tripled|scaled|closed|booked))\b", re.I)
BIG_NUMBER_WORDS = re.compile(r"\b(million|billion|crore|lakh|percent|thousand)s?\b", re.I)
NUMBER = re.compile(r"(?<![A-Za-z\d])[₹$€£]?\d[\d,\.]*\s?(?:%|[kKmMbB]\b|x\b)?")   # standalone figures, not "B2B20" or "alpha10"
PLACEHOLDER = re.compile(r"\[[^\]]*\]")


def strip_placeholders(text: str) -> str:
    return PLACEHOLDER.sub(" ", text)


def norm_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Issue:
    code: str
    severity: str     # "error" blocks "ready"; "warn" is shown but does not
    message: str


@dataclass
class Script:
    title: str = ""
    hooks: dict = field(default_factory=dict)
    hook_variants: list = field(default_factory=list)
    beats: list = field(default_factory=list)
    caption: str = ""
    hashtags: list = field(default_factory=list)
    cta: dict = field(default_factory=dict)
    needs_from_you: list = field(default_factory=list)
    framework_id: str = ""
    topic: str = ""
    angle: str = ""
    rounds: int = 0
    issues: list = field(default_factory=list)
    error: str = ""

    @property
    def spoken(self) -> str:
        return " ".join(b["spoken"] for b in self.beats if b.get("spoken"))

    @property
    def status(self) -> str:
        if self.error:
            return "failed"
        return "needs_work" if any(i.severity == "error" for i in self.issues) else "ready"

    def est_seconds(self, wps: float) -> float:
        return len(self.spoken.split()) / wps if wps else 0.0

    def all_text(self) -> str:
        parts = [self.title, self.caption, self.cta.get("text", ""), *self.hooks.values(), self.spoken]
        parts += [b.get("on_screen_text", "") for b in self.beats]
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["issues"] = [i.__dict__ for i in self.issues]
        d["status"] = self.status
        return d


def _s(x) -> str:
    return str(x).strip() if x is not None else ""


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x) -> list:
    return x if isinstance(x, list) else []


def normalize_script(raw: dict, vocab: dict, topic: str, angle: str, framework_id: str) -> Script:
    """Model output is untrusted: any field may be missing or the wrong shape. This never raises on shape."""
    raw = _d(raw)
    beats = []
    for b in _l(raw.get("beats"))[:14]:
        if isinstance(b, dict):
            name = _s(b.get("beat")).lower()
            beats.append({"beat": name if name in vocab["beats"] else "point",
                          "start_s": b.get("start_s") if isinstance(b.get("start_s"), (int, float)) else None,
                          "end_s": b.get("end_s") if isinstance(b.get("end_s"), (int, float)) else None,
                          "spoken": _s(b.get("spoken")), "on_screen_text": _s(b.get("on_screen_text")),
                          "visual": _s(b.get("visual")), "audio": _s(b.get("audio"))})
    h, cta = _d(raw.get("hooks")), _d(raw.get("cta"))
    variants = [{k: _s(v.get(k)) for k in ("audio", "text", "video", "why")} for v in _l(raw.get("hook_variants"))[:5] if isinstance(v, dict)]
    return Script(title=_s(raw.get("title")), hooks={k: _s(h.get(k)) for k in ("audio", "text", "video")}, hook_variants=variants,
                  beats=beats, caption=_s(raw.get("caption")), hashtags=[_s(x) for x in _l(raw.get("hashtags"))][:12],
                  cta={"type": _s(cta.get("type")), "text": _s(cta.get("text"))},
                  needs_from_you=[_s(x) for x in _l(raw.get("needs_from_you")) if _s(x)],
                  framework_id=framework_id, topic=topic, angle=angle)


def is_subsequence(required: list[str], actual: list[str]) -> bool:
    it = iter(actual)
    return all(any(a == r for a in it) for r in required)


def longest_shared_run(script_words: list[str], ref_words: list[str], min_run: int) -> tuple[int, str]:
    """Longest run of consecutive identical words, found via n-grams of length min_run (no result below min_run)."""
    if len(script_words) < min_run or len(ref_words) < min_run:
        return 0, ""
    grams = {}
    for i in range(len(ref_words) - min_run + 1):
        grams.setdefault(tuple(ref_words[i:i + min_run]), []).append(i)
    best, where = 0, 0
    for i in range(len(script_words) - min_run + 1):
        for j in grams.get(tuple(script_words[i:i + min_run]), []):
            k = min_run
            while i + k < len(script_words) and j + k < len(ref_words) and script_words[i + k] == ref_words[j + k]:
                k += 1
            if k > best:
                best, where = k, i
    return best, " ".join(script_words[where:where + best])


def unsourced_numbers(text: str, allowed: str) -> list[str]:
    """Numbers and big-number words that appear in the script but not in the brief or her material.
    Single digits (for example '3 ways') are structure, not claims. Anything inside [placeholders] is ignored."""
    text, allowed_l = strip_placeholders(text), allowed.lower()
    flagged = []
    for m in NUMBER.finditer(text):
        tok = m.group(0).strip()
        digits = re.sub(r"\D", "", tok)
        if not digits or (len(digits) == 1 and not re.search(r"[%kKmMbBx$₹€£]", tok)):
            continue
        if tok.lower().strip(".,") in allowed_l or digits in re.sub(r"\D", " ", allowed).split():
            continue
        flagged.append(tok.strip(".,"))
    for m in BIG_NUMBER_WORDS.finditer(text):
        if m.group(1).lower() not in allowed_l:
            flagged.append(m.group(0))
    return sorted(set(flagged), key=flagged.index)


def check_script(s: Script, fw: dict, cfg: dict, *, allowed_text: str, reference_transcripts: list[str], has_material: bool) -> list[Issue]:
    issues: list[Issue] = []
    err = lambda code, msg: issues.append(Issue(code, "error", msg))
    warn = lambda code, msg: issues.append(Issue(code, "warn", msg))
    wps, target = cfg["words_per_second"], cfg["target_seconds"]

    if not s.beats:
        err("no_beats", "The script has no beats.")
        return issues
    est = s.est_seconds(wps)
    if target and abs(est - target) / target > 0.25:
        err("runtime", f"The spoken script is about {est:.0f} seconds at {wps} words a second; the target is {target} seconds (allow plus or minus 25%).")

    a, t, v = (s.hooks.get(k, "") for k in ("audio", "text", "video"))
    missing = [k for k, x in (("audio", a), ("text", t), ("video", v)) if not x]
    if missing:
        err("three_hooks", f"Missing hook(s): {', '.join(missing)}. A script needs an audio hook, an on-screen text hook and a video hook.")
    if a and not (3 <= len(a.split()) <= cfg["audio_hook_max_words"]):
        err("audio_hook_length", f"The audio hook is {len(a.split())} words; keep it between 3 and {cfg['audio_hook_max_words']} so it fits the first 3 seconds.")
    if t and len(t.split()) > cfg["text_hook_max_words"]:
        err("text_hook_length", f"The on-screen text hook is {len(t.split())} words; keep it to {cfg['text_hook_max_words']} or fewer.")

    names = [b["beat"] for b in s.beats]
    if names[0] != "hook" or names[-1] != "cta":
        err("beat_order", "The first beat must be 'hook' and the last must be 'cta'.")
    elif not is_subsequence(fw["beats"], names):
        err("framework_beats", f"The beats {names} do not follow the framework's beats {fw['beats']} in order.")
    if not s.cta.get("text"):
        err("cta", "There is no call to action text.")
    timed = [(b["start_s"], b["end_s"]) for b in s.beats if b["start_s"] is not None and b["end_s"] is not None]
    backwards = any(e <= st for st, e in timed)
    overlapping = any(timed[i][1] > timed[i + 1][0] + 0.01 for i in range(len(timed) - 1))
    if backwards or overlapping:
        warn("beat_timing", "Beat timings overlap or run backwards.")

    for n in unsourced_numbers(s.all_text(), allowed_text):
        err("unsourced_number", f"'{n}' is not in your brief or your own material. Remove it or replace it with a [placeholder] for your real figure.")
    for sentence in re.split(r"(?<=[.!?])\s+", s.spoken):
        m = PERSONAL_CLAIM.search(sentence)
        if m and "[" not in sentence:
            (warn if has_material else err)("personal_claim",
                f"“{sentence.strip()[:90]}” claims a personal result or client. " +
                ("Check it matches your real material." if has_material else "Add the real example to config/my_material.md or use a [placeholder]."))

    words = norm_words(" ".join([a, t, s.spoken, s.caption]))
    for ref in reference_transcripts:
        n, snippet = longest_shared_run(words, norm_words(ref), cfg["max_shared_words"])
        if n >= cfg["max_shared_words"]:
            err("copying", f"{n} words in a row match a reference Reel: “{snippet}”. Rewrite it in your own words.")
            break
    return issues


def write_script(llm: LLM, context: dict, fw: dict, vocab: dict, cfg: dict, *, allowed_text: str, reference_transcripts: list[str],
                 has_material: bool) -> Script:
    topic, angle = context["topic"], context["angle"]["name"]
    issues: list[Issue] = []
    script = Script(topic=topic, angle=angle, framework_id=fw["id"])
    for rnd in range(1, cfg["max_rounds"] + 1):
        payload = dict(context)
        if issues:
            payload["fix_these"] = [i.message for i in issues if i.severity == "error"]
        try:
            raw = llm.complete_json(SCRIPT_SYSTEM, json.dumps(payload))
        except Exception as exc:
            script.error, script.rounds = f"script generation failed: {exc}", rnd
            return script
        try:
            script = normalize_script(raw, vocab, topic, angle, fw["id"])
            script.rounds = rnd
            issues = check_script(script, fw, cfg, allowed_text=allowed_text, reference_transcripts=reference_transcripts, has_material=has_material)
        except Exception as exc:
            script.error, script.rounds = f"the model's script could not be read: {exc}", rnd
            return script
        script.issues = issues
        if not any(i.severity == "error" for i in issues):
            break
    placeholders = [p for p in PLACEHOLDER.findall(script.all_text() + " ".join(b.get("visual", "") for b in script.beats))]
    for p in placeholders:
        if p not in script.needs_from_you:
            script.needs_from_you.append(p)
    return script
