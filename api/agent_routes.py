"""Agent-based endpoints (agent/graph.py) - a genuinely stateful, interrupt-based
LangGraph orchestration over the same engine/memory/courtroom/simworld/feedback code the
non-agent `/incidents/...` routes use (routes.py). Kept side by side, not replacing them
- see docs/DECISIONS.md AGENT1.
"""

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command

from .schemas import AgentActionRequest
from .state import AppState

router = APIRouter()


def _state(request: Request) -> AppState:
    return request.app.state.trustlens


def _find_or_404(state: AppState, incident_id: str) -> dict:
    inc = state.find(incident_id) or next((d for d in state.demo_incidents if d["id"] == incident_id), None)
    if inc is None:
        raise HTTPException(404, f"Unknown incident {incident_id!r}")
    return inc


def _log_new_audit_events(state: AppState, before_count: int, result: dict) -> None:
    """Only the events added by *this* invoke() call - the checkpointer accumulates
    audit_events across both /start and /act for the same thread_id, so re-logging the
    full list on /act would duplicate everything /start already wrote."""
    for e in result.get("audit_events", [])[before_count:]:
        state.log_event(**e)


@router.post("/agent/incidents/{incident_id}/start")
def agent_start(incident_id: str, request: Request):
    """Runs the graph from the top the FIRST time this incident is opened: gather
    context -> retrieve memory -> generate candidate actions -> trust -> (Courtroom,
    if warranted) -> pauses at the human-in-the-loop interrupt.

    Idempotent on every later call for the same incident_id (checked via the
    checkpointer, not a separate flag): if a run is already paused awaiting a human
    decision, or has already finished (executed/rejected), this replays that same
    checkpointed state instead of invoking the graph again. Revisiting
    /incidents/{id} - including React StrictMode's dev-mode double-invoke of the
    same effect - must not re-run the agent or duplicate audit events; see
    docs/DECISIONS.md AGENT5."""
    state = _state(request)
    incident = _find_or_404(state, incident_id)
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": incident_id}}

    snapshot = graph.get_state(config)
    if not snapshot.values:
        invoke_result = graph.invoke({"incident_id": incident_id, "incident": incident, "audit_events": []}, config=config)
        _log_new_audit_events(state, 0, invoke_result)
        # Re-read via get_state() rather than trusting invoke()'s own return value:
        # get_state().values is reliably the full accumulated state (same pattern
        # agent_act already used); invoke()'s return shape under an interrupt is not
        # guaranteed to carry every earlier node's merged keys the same way.
        snapshot = graph.get_state(config)

    result = snapshot.values
    awaiting_human = bool(snapshot.next)

    return {
        "incident_id": incident_id,
        "sources_analyzed": result.get("sources_analyzed"),
        "memory_results_count": result.get("memory_results_count"),
        "candidate_actions": result.get("candidate_actions"),
        "recommendation": result.get("selected_recommendation"),
        "trust_score": result.get("trust_score"),
        "trust_factors": result.get("trust_factors"),
        "similar_incidents": result.get("similar_incidents"),
        "gate_decision": result.get("gate_decision"),
        "courtroom_result": result.get("courtroom_result"),
        "courtroom_required": result.get("courtroom_required"),
        "awaiting_human": awaiting_human,
        "status": result.get("status"),
        "human_action": result.get("human_action"),
        "execution_result": result.get("execution_result"),
        "observed_outcome": result.get("observed_outcome"),
        "memory_update": result.get("memory_update"),
    }


@router.post("/agent/incidents/{incident_id}/act")
def agent_act(incident_id: str, body: AgentActionRequest, request: Request):
    """Resumes the paused graph with the human's decision. 'approve' -> execute,
    observe outcome, write the verified result back to Hindsight, all inside the same
    graph run. 'reject' -> logged, no action taken."""
    state = _state(request)
    _find_or_404(state, incident_id)
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": incident_id}}

    snapshot = graph.get_state(config)
    if not snapshot.next:
        raise HTTPException(400, f"No agent run is awaiting a human decision for {incident_id!r} "
                                 "(call /agent/start first)")
    before_count = len(snapshot.values.get("audit_events", []))

    result = graph.invoke(Command(resume=body.model_dump()), config=config)
    _log_new_audit_events(state, before_count, result)

    return {
        "incident_id": incident_id, "status": result.get("status"),
        "execution_result": result.get("execution_result"),
        "observed_outcome": result.get("observed_outcome"),
        "memory_update": result.get("memory_update"),
    }


@router.get("/agent/incidents/{incident_id}/state")
def agent_state(incident_id: str, request: Request):
    """Inspect the current checkpointed AgentState for this incident (debugging/UI
    polling) - not required for the happy path, just visibility into the same state
    LangGraph is threading through the run."""
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": incident_id}}
    snapshot = graph.get_state(config)
    if not snapshot.values:
        raise HTTPException(404, f"No agent run found for {incident_id!r}")
    values = dict(snapshot.values)
    values.pop("incident", None)  # large; the caller already has it via /incidents/{id}
    return {"awaiting_human": bool(snapshot.next), "state": values}
