"""Agent capabilities, each wrapping ALREADY-TESTED existing code (engine/, memory/,
courtroom/, simworld/, feedback/) - per the instruction to refactor into an agentic
orchestration layer, not rewrite working functionality.

Each tool takes `ctx` (the FastAPI AppState) explicitly rather than being decorated with
LangChain's `@tool` for LLM function-calling: routing in this graph is deterministic
(SPEC explicitly permits this - "the graph controls the next step based on state"), not
an LLM freely choosing which tool to call next, so a JSON-schema'd `@tool` wrapper would
be decorative rather than functional here. See docs/DECISIONS.md AGENT1.
"""

import numpy as np

import simworld
from courtroom.debate import convene, should_convene
from engine.gate import decide as gate_decide
from engine.recall_bridge import recall_candidates
from engine.scoring import rank_fixes


def get_incident_context(incident: dict) -> dict:
    """Extract the structured context an on-call engineer would actually have."""
    return {
        "service": incident["service"], "environment": incident["environment"],
        "error_signature": incident["error_signature"], "symptoms": incident["symptoms"],
        "changes_before": incident["changes_before"], "contributing_factors": incident["contributing_factors"],
        "slack_summary": incident["slack_thread"][:4],
    }


def sources_analyzed(incident: dict) -> list[str]:
    sources = ["incident payload"]
    if incident["slack_thread"]:
        sources.append("Slack")
    if incident["changes_before"]:
        sources.append("recent deployments/config changes")
    sources.append("historical memory (Hindsight)")
    return sources


def search_historical_incidents(incident: dict, ctx) -> list[dict]:
    """Hindsight recall, joined back to structured records by incident_id
    (engine/recall_bridge.py) - the actual long-term-memory read."""
    return recall_candidates(ctx.store, ctx.bank_id, incident, ctx.incidents_by_id, top_n=ctx.recall_top_n)


def generate_candidate_actions(incident: dict, candidates: list[dict], ctx) -> tuple[list[dict], str]:
    """Similarity -> two-sided evidence -> trust score -> ranking (engine/scoring.py).
    verdict_priority=True: real substantial evidence beats thin unproven high-trust
    fixes (docs/DECISIONS.md ENG-verdict-priority). Returns (ranked as plain dicts,
    weights_version) - everything crossing the graph boundary is JSON-serializable."""
    wv = ctx.current_weights()
    ranked = rank_fixes(incident, candidates, ctx.fixes_catalog, wv, ctx.engine_cfg, verdict_priority=True)
    return [fix_evidence_to_dict(fe) for fe in ranked], wv.version


def retrieve_similar_incidents(top_fix_dict: dict, limit: int = 5) -> list[dict]:
    """Curate a human-readable 'similar incidents' list from the top recommendation's
    own cited evidence (real cases, real similarity, real outcomes - not fabricated)."""
    fix = top_fix_dict["fix"]
    cases = sorted(top_fix_dict["passed"]["cases"] + top_fix_dict["failed"]["cases"], key=lambda c: -c["sim"])
    out = []
    for c in cases[:limit]:
        why_bits = []
        if c["sim"] > 0.5:
            why_bits.append("high feature similarity")
        why_bits.append(f"same fix ({fix.replace('_', ' ')}) tried")
        out.append({
            "incident_id": c["incident_id"], "similarity": round(c["sim"], 3),
            "action": fix, "outcome": c["outcome"],
            "time_to_recover_min": c.get("time_to_recover_min"),
            "why_relevant": " + ".join(why_bits),
        })
    return out


def fix_evidence_to_dict(fe) -> dict:
    """FixEvidence dataclass -> plain JSON-serializable dict, stripping the internal
    cluster_key tuples. Everything crossing the graph's state boundary goes through
    this, so the checkpointer (and a future non-in-memory one) can serialize it."""
    import dataclasses
    d = dataclasses.asdict(fe)
    for side in ("passed", "failed"):
        d[side]["cases"] = [{k: v for k, v in c.items() if k != "cluster_key"} for c in d[side]["cases"]]
    return d


def calculate_trust_factors(fe_dict: dict) -> dict:
    """Itemized, code-computed breakdown of the trust score ('why this score' - SPEC
    S6/S10: never raw LLM confidence, always structured evidence)."""
    p, f = fe_dict["passed"], fe_dict["failed"]
    return {
        "historical_similarity": p["mean_top_sim"], "verdict": fe_dict["verdict"],
        "passed_cases": p["count"], "failed_cases": f["count"],
        "sum_similarity_passed": p["sum_sim"], "sum_similarity_failed": f["sum_sim"],
        "risk_tier": fe_dict["risk_tier"],
    }


def gate_for(fe_dict: dict, environment: str, gate_cfg: dict) -> dict:
    import dataclasses
    gate = gate_decide(fe_dict["fix"], fe_dict["risk_tier"], environment, fe_dict["verdict"],
                       fe_dict["trust"], gate_cfg)
    return dataclasses.asdict(gate)


def run_courtroom(fe_dict: dict, force: bool = False) -> dict | None:
    """Multi-agent Courtroom (Advocate/Challenger, independent OpenRouter models) -
    only when should_convene() says the recommendation actually needs a second look."""
    if not force and not should_convene(fe_dict["risk_tier"], fe_dict["verdict"], fe_dict["trust"]):
        return None
    import dataclasses
    result = convene(fe_dict["fix"], fe_dict["risk_tier"], fe_dict["verdict"], fe_dict["trust"],
                     fe_dict["passed"], fe_dict["failed"])
    return dataclasses.asdict(result)


def execute_remediation(incident: dict, fix: str, ctx, *, writer: str, authorized: bool):
    """Execute + observe outcome + write verified result back to Hindsight - all one
    call, because that's how the real system already correctly sequences it
    (simworld.run_fix -> feedback.loop.apply_outcome): the outcome must be *verified*
    before memory is updated (the poisoning guard), so 'observe' and 'update memory'
    aren't actually separable steps for a real writer, only for an unverified/rejected
    one (which never reaches memory - see feedback/loop.py)."""
    if incident not in ctx.incidents:
        ctx.incidents.append(incident)
        ctx.incidents_by_id[incident["id"]] = incident
    return simworld.run_fix(
        incident, fix, writer=writer, authorized=authorized, store=ctx.store, bank_id=ctx.bank_id,
        incidents=ctx.incidents, fixes=ctx.fix_names, engine_cfg=ctx.engine_cfg,
        weights_root=ctx.weights_root, rng=np.random.default_rng(),
    )
