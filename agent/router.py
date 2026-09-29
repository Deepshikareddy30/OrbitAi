"""Conditional routing (SPEC: 'the graph controls the next step based on state').
Deterministic, not LLM-driven - explicitly permitted ('routing can be deterministic
where appropriate'); reuses courtroom.debate.should_convene, the same rule the
non-agent /courtroom endpoint uses, so both paths agree on when a second look is needed.
"""

from courtroom.debate import should_convene


def route_after_trust(state: dict) -> str:
    fe = state["candidate_actions"][0] if state.get("candidate_actions") else None
    if fe and should_convene(fe["risk_tier"], fe["verdict"], fe["trust"]):
        return "courtroom"
    return "present"


def route_after_human_action(state: dict) -> str:
    decision = (state.get("human_action") or {}).get("decision")
    if decision == "approve":
        return "execute"
    if decision == "reject":
        return "rejected"
    return "awaiting_human"  # "investigate" (or anything else) - stay put, no action taken
