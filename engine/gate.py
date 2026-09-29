"""Adaptive approval gate (SPEC S6): routes by fix risk, verdict, trust and environment.

Fast and tiered by blast radius/reversibility - never a change-board. Pure functions
over an engine.scoring.FixEvidence (or its fields), no Hindsight/hidden dependency.
"""

import dataclasses
from dataclasses import dataclass
from typing import Optional

# Ordered least -> most restrictive. "break_glass" is a separate emergency path, not
# part of this ordering (see break_glass() below).
LEVELS = ["auto_run", "one_click", "escalate_ic", "two_person"]
LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

NOTIFY = {
    "auto_run": "on_call",           # notified, not asked to approve
    "one_click": "on_call",
    "escalate_ic": "incident_commander",
    "two_person": "two_person",
    "break_glass": "incident_commander",
}

VERDICT_FLOOR = {"conflict", "no_evidence"}  # SPEC S6: force at least one-click human approval


@dataclass
class GateDecision:
    fix: str
    risk_tier: str
    environment: str
    verdict: str
    trust: float
    action: str                      # one of LEVELS, or "break_glass"
    notify: str                      # who is notified/asked to approve
    reason: str
    timeout_min: Optional[int] = None
    requires_post_incident_review: bool = False
    relaxed_for_staging: bool = False
    floored_by_verdict: bool = False


def _base_action(risk_tier: str, verdict: str, trust: float, cfg: dict) -> str:
    rules = cfg["risk_rules"][risk_tier]
    if verdict == "agree_trust" and trust >= rules["trust_threshold"]:
        return rules["if_trusted"]
    return rules["otherwise"]


def _relax_one_level(action: str) -> str:
    idx = LEVEL_RANK[action]
    return LEVELS[max(0, idx - 1)]


def decide(fix: str, risk_tier: str, environment: str, verdict: str, trust: float, cfg: dict) -> GateDecision:
    """SPEC S6: base table -> staging relaxes one level -> conflict/no_evidence floor
    to at least one_click (applied last, so it always wins)."""
    action = _base_action(risk_tier, verdict, trust, cfg)
    relaxed = False
    if environment == "staging" and action != LEVELS[0]:
        action = _relax_one_level(action)
        relaxed = True

    floored = False
    if verdict in VERDICT_FLOOR and LEVEL_RANK[action] < LEVEL_RANK["one_click"]:
        action = "one_click"
        floored = True

    reason_bits = [f"{risk_tier} risk, verdict={verdict}, T={trust:.2f}"]
    if relaxed:
        reason_bits.append("relaxed one level (staging)")
    if floored:
        reason_bits.append("floored to one-click (conflict/no-evidence verdict)")

    return GateDecision(
        fix=fix, risk_tier=risk_tier, environment=environment, verdict=verdict, trust=trust,
        action=action, notify=NOTIFY[action], reason="; ".join(reason_bits),
        timeout_min=cfg["timeouts_min"].get(action), relaxed_for_staging=relaxed, floored_by_verdict=floored,
    )


def escalate_on_timeout(decision: GateDecision, elapsed_min: float) -> GateDecision:
    """If nobody responded within timeout_min, bump to the next-more-restrictive tier
    (simulated timer - SPEC S6)."""
    if decision.timeout_min is None or elapsed_min < decision.timeout_min:
        return decision
    idx = LEVEL_RANK.get(decision.action)
    if idx is None or idx >= len(LEVELS) - 1:
        return decision
    new_action = LEVELS[idx + 1]
    return dataclasses.replace(
        decision, action=new_action, notify=NOTIFY[new_action],
        reason=decision.reason + f"; escalated after {elapsed_min:.0f}min unanswered timeout",
        timeout_min=None,  # no further auto-escalation after this simulated bump
    )


def break_glass(fix: str, risk_tier: str, environment: str, actor: str, reason: str) -> GateDecision:
    """Emergency override path: bypasses the normal gate, but always requires a
    post-incident review entry (SPEC S6)."""
    return GateDecision(
        fix=fix, risk_tier=risk_tier, environment=environment, verdict="break_glass", trust=0.0,
        action="break_glass", notify=NOTIFY["break_glass"],
        reason=f"BREAK GLASS by {actor}: {reason}", timeout_min=None,
        requires_post_incident_review=True,
    )
