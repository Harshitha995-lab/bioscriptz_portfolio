"""Step 4 for a single request: a fresh script for a topic, or a remix of one specific outlier's structure, saved to the vault."""
from __future__ import annotations

from types import SimpleNamespace

from .formats import load_board
from .frameworks import LEVEL_RANK, pick_framework, uses
from .llm import LLM
from .script_run import ScriptResult, has_real_material, make_context, reference_brief
from .scriptwriter import Issue, Script, write_script
from .vault import Vault
from .viral_analysis import analyse_reels, build_features


def _ensure_breakdown(vault: Vault, reel, llm: LLM, vocab: dict, frames=None):
    bd = vault.breakdowns([reel.id]).get(reel.id)
    if bd is None:
        bd = analyse_reels([reel], llm, vocab, frames)[reel.id]
        vault.save_breakdown(bd)
    return bd


def write_one(vault: Vault, llm: LLM, vocab: dict, brief: str, material: str, cfg: dict, *, topic: str, niche: str = "",
              from_reel_id: str | None = None, angle: str | None = None, angle_meanings: dict | None = None,
              frames=None) -> tuple[int, ScriptResult]:
    """Returns (vault id, result). With from_reel_id the script is a REMIX: it keeps that Reel's structure and is about `topic`."""
    board = load_board(vault)
    all_transcripts = [r.transcript for r in vault.reels() if r.transcript]
    has_material = has_real_material(material)
    source = None
    if from_reel_id:
        source = vault.get_reel(from_reel_id)
        if source is None:
            raise ValueError(f"No Reel with id '{from_reel_id}' in the vault. Run `agent.py outliers` to see ids.")
        bd = _ensure_breakdown(vault, source, llm, vocab, frames)
        if bd.error:
            raise ValueError(f"The source Reel could not be analysed: {bd.error}")
        feats = build_features(source, bd, vocab)
        matching = [e for e in board if uses(e.fw, feats)]
        ev = max(matching, key=lambda e: LEVEL_RANK[e.level]) if matching else pick_framework(board, angle or "authority", {})
    else:
        ev = pick_framework(board, angle or "authority", {})
    if ev is None:
        raise ValueError("No storytelling frameworks are configured (config/frameworks.json).")
    angle_name = angle or (ev.fw.get("angles") or ["authority"])[0]

    cached = vault.breakdowns()
    ref_reels = [source] if source else []
    pool = sorted((r for r in vault.reels() if r.id in cached and not cached[r.id].error and uses(ev.fw, build_features(r, cached[r.id], vocab))
                   and (not source or r.id != source.id)), key=lambda r: -r.plays)
    ref_reels += pool[: 3 - len(ref_reels)]
    remix = None
    if source:
        remix = {"instruction": "Keep this Reel's structure (hook types, loop, beats) but write about the new topic in the founder's own voice. "
                                "Do not reuse its subject matter, examples or wording.", "source_structure": reference_brief(cached.get(source.id) or bd)}
    context = make_context(topic=topic, angle_name=angle_name, angle_meaning=(angle_meanings or {}).get(angle_name, ""), pitch="", hook="", ev=ev,
                           refs_briefs=[reference_brief(cached[r.id]) for r in ref_reels if r.id in cached and not cached[r.id].error] or
                                       ([reference_brief(bd)] if source else []),
                           brief=brief, material=material, has_material=has_material, cfg=cfg, remix=remix)
    allowed = "\n".join([brief, material if has_material else "", ev.fw["shape"], topic])
    script = write_script(llm, context, ev.fw, vocab, cfg, allowed_text=allowed, reference_transcripts=all_transcripts, has_material=has_material)
    refs = [{"account": r.account, "url": r.url, "plays": r.plays} for r in ref_reels]
    sid = vault.add_script(script.to_dict(), niche=niche, source_reel_id=from_reel_id or "", framework_level=ev.level,
                           extra={"framework": {"name": ev.fw["name"], "level": ev.level, "reasons": ev.reasons}, "references": refs,
                                  "remix_of": from_reel_id or ""})
    return sid, ScriptResult(script, ev, ref_reels, "data")


def rebuild_result(row: dict) -> ScriptResult:
    """A stored script, ready for render_script()."""
    d = dict(row["data"])
    issues = [Issue(**i) for i in d.pop("issues", [])]
    d.pop("status", None)
    fields = {k: d[k] for k in Script.__dataclass_fields__ if k in d}
    script = Script(**fields)
    script.issues = issues
    fw = d.get("framework", {})
    ev = SimpleNamespace(fw={"name": fw.get("name", row["framework_id"])}, level=fw.get("level", row["framework_level"]), reasons=fw.get("reasons", []))
    refs = [SimpleNamespace(**r) for r in d.get("references", [])]
    return ScriptResult(script, ev, refs, "data")
