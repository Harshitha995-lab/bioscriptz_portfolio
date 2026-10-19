"""Pick a framework and references for each shortlisted topic, then write and check a script."""
from __future__ import annotations

from dataclasses import dataclass, field

from .frameworks import Evidence, pick_framework, uses
from .llm import LLM
from .scriptwriter import Script, write_script
from .viral_analysis import ViralBreakdown


@dataclass
class ScriptResult:
    script: Script
    evidence: Evidence | None
    references: list = field(default_factory=list)
    slot: str = "data"


def reference_brief(bd: ViralBreakdown) -> dict:
    """How a winner was built, deliberately without any of its words."""
    h = bd.hooks
    return {"audio_hook_type": h["audio"]["type"] if h["audio"]["analysed"] else None,
            "text_hook_type": h["text"]["type"] if h["text"]["analysed"] else None,
            "video_hook_type": h["video"]["type"] if h["video"]["analysed"] else None,
            "format": bd.format, "loop": bd.loop.get("type"), "beats": [b["beat"] for b in bd.structure],
            "spice": bd.spice, "cta_type": bd.cta.get("type")}


def choose_references(fw: dict, library: list, features: dict, topic: str, k: int = 3) -> list:
    matching = [r for r in library if uses(fw, features.get(r.id, {}))]
    pool = matching or list(library)
    return sorted(pool, key=lambda r: (r.topic.lower() != topic.lower(), -r.heat))[:k]


def generate_scripts(picks: list, board: list[Evidence], library: list, breakdowns: dict, features: dict, angle_meanings: dict,
                     llm: LLM, vocab: dict, brief: str, material: str, cfg: dict) -> list[ScriptResult]:
    has_material = bool(material.strip()) and "(empty for now" not in material
    all_transcripts = [r.transcript for r in library if r.transcript]     # copy check runs against every winner, not just the references
    out, used = [], {}
    for pick in picks[: cfg["count"]]:
        if not pick.angles:
            continue
        idea = pick.angles[0]
        ev = pick_framework(board, idea.angle, used, experiment=pick.slot == "experiment", cap=cfg.get("max_per_framework", 2))
        if ev is None:
            continue
        used[ev.fw["id"]] = used.get(ev.fw["id"], 0) + 1
        refs = choose_references(ev.fw, library, features, pick.topic.name)
        context = {
            "brand_brief": brief, "my_material": material if has_material else "(none provided: use [placeholders] for any personal story or result)",
            "topic": pick.topic.name,
            "angle": {"name": idea.angle, "meaning": angle_meanings.get(idea.angle, ""), "pitch": idea.pitch, "suggested_hook": idea.hook},
            "framework": {"name": ev.fw["name"], "shape": ev.fw["shape"], "beats": ev.fw["beats"], "hook_formula": ev.fw["hook_formula"],
                          "evidence_level": ev.level, "evidence": ev.reasons},
            "references": [reference_brief(breakdowns[r.id]) for r in refs if r.id in breakdowns and not breakdowns[r.id].error],
            "constraints": {"target_seconds": cfg["target_seconds"], "words_per_second": cfg["words_per_second"],
                            "audio_hook_max_words": cfg["audio_hook_max_words"], "text_hook_max_words": cfg["text_hook_max_words"]},
        }
        allowed = "\n".join([brief, material if has_material else "", ev.fw["shape"], pick.topic.name])
        script = write_script(llm, context, ev.fw, vocab, cfg, allowed_text=allowed, reference_transcripts=all_transcripts, has_material=has_material)
        out.append(ScriptResult(script, ev, refs, pick.slot))
    return out
