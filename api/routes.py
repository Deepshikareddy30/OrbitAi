"""REST routes (SPEC S2 UI row, S8 demo upload, S10.4 where things appear).

Never reads the ground-truth folder directly - execute/poison go through simworld,
which is the only boundary allowed to look up ground truth. See tests/test_hidden_leak.py.
"""

import dataclasses
import json
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Request

import simworld
from courtroom.debate import convene, should_convene
from engine import features as F
from engine.gate import decide as gate_decide
from engine.recall_bridge import recall_candidates
from engine.scoring import rank_fixes
from engine.weights import list_versions, load

from .schemas import CourtroomRequest, ExecuteFixRequest, PoisonRequest
from .state import AppState, reset_state

router = APIRouter()
_EVAL_RESULTS_PATH = Path(__file__).resolve().parent.parent / "eval" / "results.json"


def _state(request: Request) -> AppState:
    return request.app.state.trustlens


def _summary(inc: dict) -> dict:
    return {"id": inc["id"], "timestamp": inc["timestamp"], "service": inc["service"],
           "environment": inc["environment"], "error_signature": inc["error_signature"],
           "split": inc["split"], "n_attempts": len(inc["attempts"])}


def _find_or_404(state: AppState, incident_id: str) -> dict:
    inc = state.find(incident_id) or next((d for d in state.demo_incidents if d["id"] == incident_id), None)
    if inc is None:
        raise HTTPException(404, f"Unknown incident {incident_id!r}")
    return inc


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/fixes")
def fixes(request: Request):
    return _state(request).fixes_catalog


@router.get("/gate/config")
def gate_config(request: Request):
    return _state(request).gate_cfg


@router.get("/incidents")
def list_incidents(request: Request, split: str | None = None, q: str | None = None,
                   limit: int = 100, offset: int = 0):
    state = _state(request)
    items = state.incidents if split is None else [i for i in state.incidents if i["split"] == split]
    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in i["id"].lower() or needle in i["service"].lower()
                or needle in i["error_signature"].lower()]
    return {"count": len(items), "offset": offset, "limit": limit,
           "incidents": [_summary(i) for i in items[offset:offset + limit]]}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, request: Request):
    state = _state(request)
    inc = state.find(incident_id) or next((d for d in state.demo_incidents if d["id"] == incident_id), None)
    if inc is None:
        raise HTTPException(404, f"Unknown incident {incident_id!r}")
    return inc


@router.get("/demo/incidents")
def demo_incidents(request: Request):
    return _state(request).demo_incidents


@router.post("/demo/reset")
def demo_reset(request: Request):
    state = _state(request)
    reset_state(state)
    return {"status": "reset", "weights_version": state.current_weights().version,
           "bank_id": state.bank_id, "n_incidents": len(state.incidents)}


def _evidence_to_dict(fe) -> dict:
    d = dataclasses.asdict(fe)
    for side in ("passed", "failed"):
        d[side]["cases"] = [{k: v for k, v in c.items() if k != "cluster_key"} for c in d[side]["cases"]]
    return d


@router.get("/incidents/{incident_id}/recommendation")
def recommendation(incident_id: str, request: Request):
    state = _state(request)
    present = state.find(incident_id) or next((d for d in state.demo_incidents if d["id"] == incident_id), None)
    if present is None:
        raise HTTPException(404, f"Unknown incident {incident_id!r}")

    wv = state.current_weights()
    candidates = recall_candidates(state.store, state.bank_id, present, state.incidents_by_id,
                                   top_n=state.recall_top_n)
    ranked = rank_fixes(present, candidates, state.fixes_catalog, wv, state.engine_cfg)
    risk_by_fix = {f["fix"]: f["risk_tier"] for f in state.fixes_catalog}

    results = []
    for fe in ranked:
        gate = gate_decide(fe.fix, fe.risk_tier, present["environment"], fe.verdict, fe.trust, state.gate_cfg)
        results.append({"evidence": _evidence_to_dict(fe), "gate": dataclasses.asdict(gate)})

    state.log_event("gate_decision", incident_id=incident_id,
                    top_fix=ranked[0].fix if ranked else None,
                    verdict=ranked[0].verdict if ranked else None,
                    action=results[0]["gate"]["action"] if results else None)

    return {"incident_id": incident_id, "weights_version": wv.version,
           "n_candidates": len(candidates), "ranked_fixes": results}


@router.post("/incidents/{incident_id}/courtroom")
def courtroom(incident_id: str, body: CourtroomRequest, request: Request):
    """Advocate + Challenger independently argue over the already-computed evidence for
    one fix (default: the top verdict-priority recommendation). Only convenes when risk
    is high, evidence conflicts, or trust is low (should_convene()) - pass force=true to
    override for the demo. The trust adjustment shown is 100% code-computed from the real
    evidence (courtroom/debate.py::assess()) - the two LLM calls only produce the
    human-readable argument text.
    """
    state = _state(request)
    present = _find_or_404(state, incident_id)

    wv = state.current_weights()
    candidates = recall_candidates(state.store, state.bank_id, present, state.incidents_by_id,
                                   top_n=state.recall_top_n)
    ranked = rank_fixes(present, candidates, state.fixes_catalog, wv, state.engine_cfg, verdict_priority=True)
    if not ranked:
        raise HTTPException(400, "No recalled evidence to convene a courtroom over")
    fe = next((f for f in ranked if f.fix == body.fix), ranked[0]) if body.fix else ranked[0]

    if not body.force and not should_convene(fe.risk_tier, fe.verdict, fe.trust):
        return {"convened": False, "fix": fe.fix, "risk_tier": fe.risk_tier, "verdict": fe.verdict,
               "trust": fe.trust,
               "reason": "Risk is not high, evidence doesn't conflict, and trust is above threshold - "
                        "the Courtroom only convenes when a recommendation actually needs a second look."}

    evidence = _evidence_to_dict(fe)
    result = convene(fe.fix, fe.risk_tier, fe.verdict, fe.trust, evidence["passed"], evidence["failed"])
    state.log_event("courtroom_convened", incident_id=incident_id, fix=fe.fix,
                    base_trust=result.base_trust, final_trust=result.final_trust,
                    advocate_used_llm=result.advocate_used_llm, challenger_used_llm=result.challenger_used_llm)
    return dataclasses.asdict(result)


@router.post("/incidents/{incident_id}/execute")
def execute(incident_id: str, body: ExecuteFixRequest, request: Request):
    state = _state(request)
    inc = state.find(incident_id) or next((d for d in state.demo_incidents if d["id"] == incident_id), None)
    if inc is None:
        raise HTTPException(404, f"Unknown incident {incident_id!r}")
    if inc not in state.incidents:
        state.incidents.append(inc)
        state.incidents_by_id[inc["id"]] = inc

    try:
        result = simworld.run_fix(
            inc, body.fix, writer=body.writer, authorized=body.authorized, store=state.store,
            bank_id=state.bank_id, incidents=state.incidents, fixes=state.fix_names,
            engine_cfg=state.engine_cfg, weights_root=state.weights_root,
            rng=np.random.default_rng(), human_override=body.human_override,
            override_reason=body.override_reason,
        )
    except KeyError as e:
        raise HTTPException(400, str(e)) from e

    for event in result.audit_events:
        state.log_event(**event)
    state.log_event("recommendation_verified", incident_id=incident_id, fix=body.fix,
                    outcome=result.outcome, verified=result.verified, accepted=result.accepted)
    if body.human_override:
        state.log_event("human_override", incident_id=incident_id, fix=body.fix,
                        reason=body.override_reason)

    return dataclasses.asdict(result)


@router.post("/incidents/{incident_id}/poison")
def poison(incident_id: str, body: PoisonRequest, request: Request):
    """Demo endpoint for the required poisoning-guard demo (SPEC S7)."""
    state = _state(request)
    inc = state.find(incident_id) or next((d for d in state.demo_incidents if d["id"] == incident_id), None)
    if inc is None:
        raise HTTPException(404, f"Unknown incident {incident_id!r}")
    if inc not in state.incidents:
        state.incidents.append(inc)
        state.incidents_by_id[inc["id"]] = inc

    result = simworld.poison_attempt(
        inc, body.fix, body.outcome, writer=body.writer, authorized=body.authorized,
        verified=body.verified, store=state.store, bank_id=state.bank_id, incidents=state.incidents,
        fixes=state.fix_names, engine_cfg=state.engine_cfg, weights_root=state.weights_root,
    )
    for event in result.audit_events:
        state.log_event(**event)
    return dataclasses.asdict(result)


@router.get("/weights/versions")
def weight_versions(request: Request):
    state = _state(request)
    return {"versions": list_versions(state.weights_root)}


@router.get("/weights/{version}")
def weight_version(version: str, request: Request):
    state = _state(request)
    try:
        wv = load(state.weights_root, version)
    except FileNotFoundError:
        raise HTTPException(404, f"Unknown weights version {version!r}")
    return dataclasses.asdict(wv)


@router.get("/eval/results")
def eval_results():
    """SPEC S10.3/S10.4: the one results.json, read by AI Health/incident-level eval.
    Serves the file as-is - nothing is recomputed here (DECISIONS API4)."""
    if not _EVAL_RESULTS_PATH.exists():
        raise HTTPException(404, "eval/results.json not found - run `python -m eval.run` first")
    return json.loads(_EVAL_RESULTS_PATH.read_text(encoding="utf-8"))


@router.get("/audit")
def audit_log(request: Request, event: str | None = None, limit: int = 200):
    state = _state(request)
    items = state.audit_log if event is None else [e for e in state.audit_log if e["event"] == event]
    return {"count": len(items), "events": items[-limit:]}
