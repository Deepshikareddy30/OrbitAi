"""The LangGraph incident-response agent.

gather_context -> analyze_evidence -> build_recommendation -> [courtroom?] ->
present_recommendation --(interrupt: waits for the human)--> execute | rejected

One compiled graph per process (built once in api/app.py, closing over the shared
AppState - see tools.py's module docstring for why). A checkpointer (InMemorySaver)
keyed by thread_id=incident_id carries state across the two HTTP calls
(POST .../agent/start, POST .../agent/act) that straddle the human-in-the-loop
interrupt - this is what makes it a genuinely stateful, paused-and-resumed agent
rather than two independent stateless calls (SPEC S8: "Do NOT create independent
stateless LLM calls where every function starts from scratch").
"""

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from courtroom.debate import should_convene

from . import tools
from .router import route_after_human_action, route_after_trust
from .state import AgentState

log = logging.getLogger("agent.graph")


def build_graph(ctx):
    """`ctx` is the FastAPI AppState - closed over by every node below, so nodes stay
    thin (one call into agent/tools.py, one state update) while still reaching live
    Hindsight/engine/gate config without stuffing infra objects into the graph state.
    """

    def gather_context(state: AgentState) -> dict:
        incident = state["incident"]
        return {
            "incident_context": tools.get_incident_context(incident),
            "sources_analyzed": tools.sources_analyzed(incident),
            "status": "analyzing",
            "audit_events": [{"event": "incident_context_gathered", "incident_id": incident["id"]}],
        }

    def analyze_evidence(state: AgentState) -> dict:
        incident = state["incident"]
        candidates = tools.search_historical_incidents(incident, ctx)
        ranked, weights_version = tools.generate_candidate_actions(incident, candidates, ctx)
        return {
            "memory_results_count": len(candidates), "candidate_actions": ranked,
            "audit_events": [
                {"event": "memory_retrieved", "incident_id": incident["id"], "count": len(candidates)},
                {"event": "candidate_actions_generated", "incident_id": incident["id"], "n": len(ranked),
                 "weights_version": weights_version},
            ],
        }

    def build_recommendation(state: AgentState) -> dict:
        incident = state["incident"]
        ranked = state["candidate_actions"]
        top = ranked[0] if ranked else None
        if top is None:
            return {"selected_recommendation": None, "trust_score": None, "trust_factors": None,
                    "similar_incidents": [], "gate_decision": None, "courtroom_required": False,
                    "audit_events": [{"event": "no_recommendation", "incident_id": incident["id"]}]}
        similar = tools.retrieve_similar_incidents(top)
        gate = tools.gate_for(top, incident["environment"], ctx.gate_cfg)
        required = should_convene(top["risk_tier"], top["verdict"], top["trust"])
        return {
            "selected_recommendation": top, "trust_score": top["trust"],
            "trust_factors": tools.calculate_trust_factors(top), "similar_incidents": similar,
            "gate_decision": gate, "courtroom_required": required,
            "audit_events": [
                {"event": "recommendation_selected", "incident_id": incident["id"], "fix": top["fix"],
                 "trust": top["trust"], "verdict": top["verdict"]},
                {"event": "trust_calculated", "incident_id": incident["id"], "trust": top["trust"]},
            ],
        }

    def courtroom_node(state: AgentState) -> dict:
        incident = state["incident"]
        top = state["selected_recommendation"]
        result = tools.run_courtroom(top, force=True)  # already gated by route_after_trust
        return {
            "courtroom_result": result,
            "audit_events": [{"event": "courtroom_convened", "incident_id": incident["id"], "fix": top["fix"],
                             "base_trust": result["base_trust"], "final_trust": result["final_trust"]}],
        }

    def present_recommendation(state: AgentState) -> dict:
        payload = {
            "recommendation": state["selected_recommendation"], "trust_score": state["trust_score"],
            "trust_factors": state["trust_factors"], "similar_incidents": state["similar_incidents"],
            "gate_decision": state["gate_decision"], "courtroom_result": state.get("courtroom_result"),
        }
        human_action = interrupt(payload)
        return {"human_action": human_action, "status": "awaiting_human",
               "audit_events": [{"event": "human_action_received", "incident_id": state["incident"]["id"],
                                "decision": (human_action or {}).get("decision")}]}

    def execute_node(state: AgentState) -> dict:
        incident = state["incident"]
        action = state["human_action"] or {}
        fix = action.get("fix") or state["selected_recommendation"]["fix"]
        result = tools.execute_remediation(incident, fix, ctx, writer=action.get("writer", "on-call-engineer"),
                                           authorized=action.get("authorized", True))
        observed = {"outcome": result.outcome, "time_to_recover_min": result.time_to_recover_min,
                   "verified": result.verified, "recurred_within_24h": result.recurred_within_24h}
        memory_update = {"retained": True, "accepted": result.accepted, "reason": result.reason,
                         "weights_version": result.weights_version}
        return {
            "execution_result": {"fix": fix, "outcome": result.outcome, "accepted": result.accepted},
            "observed_outcome": observed, "memory_update": memory_update, "status": "done",
            "audit_events": [{"event": "action_executed", "incident_id": incident["id"], "fix": fix,
                             "outcome": result.outcome},
                            {"event": "outcome_observed", "incident_id": incident["id"], **observed},
                            {"event": "memory_updated", "incident_id": incident["id"], **memory_update}]
            + result.audit_events,
        }

    def rejected_node(state: AgentState) -> dict:
        incident = state["incident"]
        action = state["human_action"] or {}
        return {"status": "rejected",
               "audit_events": [{"event": "action_rejected", "incident_id": incident["id"],
                                "reason": action.get("reason")}]}

    graph = StateGraph(AgentState)
    graph.add_node("gather_context", gather_context)
    graph.add_node("analyze_evidence", analyze_evidence)
    graph.add_node("build_recommendation", build_recommendation)
    graph.add_node("courtroom", courtroom_node)
    graph.add_node("present_recommendation", present_recommendation)
    graph.add_node("execute", execute_node)
    graph.add_node("rejected", rejected_node)

    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "analyze_evidence")
    graph.add_edge("analyze_evidence", "build_recommendation")
    graph.add_conditional_edges("build_recommendation", route_after_trust,
                                {"courtroom": "courtroom", "present": "present_recommendation"})
    graph.add_edge("courtroom", "present_recommendation")
    graph.add_conditional_edges("present_recommendation", route_after_human_action,
                                {"execute": "execute", "rejected": "rejected", "awaiting_human": END})
    graph.add_edge("execute", END)
    graph.add_edge("rejected", END)

    return graph.compile(checkpointer=InMemorySaver())
