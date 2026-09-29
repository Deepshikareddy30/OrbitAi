"""Shared state threaded through the LangGraph incident-response agent.

Every field here is plain, JSON-serializable data - no live infra objects (MemoryStore,
weights version, etc.) live in state. Nodes reach shared infra (Hindsight, engine config,
fixes catalog) via a closure over the FastAPI AppState at graph-build time (agent/graph.py),
not through the graph state itself - keeps the state genuinely inspectable/serializable
and matches how a real production LangGraph app separates "workflow data" from
"service dependencies".
"""

import operator
from typing import Annotated, Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    incident_id: str
    incident: dict                       # the raw incident record

    incident_context: dict               # {symptoms, changes_before, slack_summary, ...}
    sources_analyzed: list[str]          # ["incident payload", "slack", "deployments", ...]

    memory_results_count: int            # how many candidates Hindsight recall returned
    similar_incidents: list[dict]        # curated: [{incident_id, similarity, action, outcome, why}]

    candidate_actions: list[dict]        # ranked FixEvidence, as plain dicts
    selected_recommendation: Optional[dict]  # the top candidate_actions entry
    trust_score: Optional[float]
    trust_factors: Optional[dict]        # itemized, code-computed breakdown ("why this score")

    courtroom_required: bool
    courtroom_result: Optional[dict]

    gate_decision: Optional[dict]

    human_action: Optional[dict]         # {decision: approve|reject|investigate, fix}
    execution_result: Optional[dict]     # simworld/feedback FeedbackResult, as a dict
    observed_outcome: Optional[dict]     # {outcome, time_to_recover_min, verified}
    memory_update: Optional[dict]        # {retained: bool, weights_version, reflect_text}

    # Reducer: nodes append rather than overwrite (LangGraph merges list-typed fields
    # via the given operator when a node returns a partial update for this key).
    audit_events: Annotated[list[dict], operator.add]

    status: str  # "analyzing" | "awaiting_human" | "executing" | "done" | "rejected"
