"""Courtroom orchestration (SPEC-extension: high-risk/conflicting/low-confidence
recommendations only - not every incident).

The trust adjustment and every Courtroom Assessment label are computed in plain code
from the already-real FixEvidence (assess()). The two LLM calls (advocate()/
challenger()) only produce human-readable argument text over that same evidence - they
never see or touch the numbers themselves, and a call failure never blocks the
assessment (falls back to a template sentence built from the real evidence).
"""

import logging
from dataclasses import asdict, dataclass

from . import llm_client

log = logging.getLogger("courtroom.debate")

TRUST_THRESHOLD = 0.60  # below this, a recommendation is "low confidence" enough to convene
MAX_ADJUSTMENT = 0.10   # the courtroom can move trust by at most this much, either direction


def should_convene(risk_tier: str, verdict: str, trust: float) -> bool:
    """Risk is high, OR evidence conflicts, OR confidence is below threshold."""
    return risk_tier == "high" or verdict == "conflict" or trust < TRUST_THRESHOLD


def _case_lines(cases: list[dict], limit: int = 3) -> str:
    if not cases:
        return "  (none)"
    return "\n".join(
        f"  - {c['incident_id']}: {c['outcome']}, similarity {c['sim']:.2f}"
        + (f", recovered in {c['time_to_recover_min']}m" if c.get("time_to_recover_min") else "")
        for c in cases[:limit]
    )


def _evidence_summary(fix: str, risk_tier: str, verdict: str, trust: float, passed: dict, failed: dict) -> str:
    return (
        f"Recommended fix: {fix.replace('_', ' ')}\n"
        f"Risk tier: {risk_tier}\n"
        f"Computed verdict: {verdict}\n"
        f"Computed trust score: {trust:.0%}\n\n"
        f"Cases where this fix PASSED ({passed['count']} total, mean similarity "
        f"{passed['mean_top_sim']:.2f}):\n{_case_lines(passed['cases'])}\n\n"
        f"Cases where this fix FAILED or recurred ({failed['count']} total, mean similarity "
        f"{failed['mean_top_sim']:.2f}):\n{_case_lines(failed['cases'])}"
    )


_OUTPUT_RULES = (
    "Output ONLY the argument itself as 1-3 short sentences of plain English. "
    "Do not narrate the task, the instructions, or your own reasoning process. Do not "
    "write phrases like 'I need to', 'let me', 'the instruction says', or 'I should' - "
    "just state the argument directly, as if speaking in a meeting. Do not use headers, "
    "labels, or markdown."
)
ADVOCATE_SYSTEM = (
    "You are the Advocate in an incident-response review. You argue FOR trusting the "
    "given recommendation, using ONLY the evidence provided - cite real case IDs from it. "
    + _OUTPUT_RULES
)
CHALLENGER_SYSTEM = (
    "You are the Challenger in an incident-response review. You argue for CAUTION about "
    "the given recommendation, using ONLY the evidence provided - point out what could make "
    "the historical support less reliable than it looks (timing, recency, differing root "
    "cause, thin evidence). Cite real case IDs from it. " + _OUTPUT_RULES
)


def _fallback_advocate(passed: dict, verdict: str) -> str:
    if passed["count"] == 0:
        return "No historical passes are on record for this fix against similar incidents."
    ids = ", ".join(c["incident_id"] for c in passed["cases"][:3])
    return (f"{passed['count']} similar past incident(s) ({ids}) were resolved with this fix, "
           f"at {passed['mean_top_sim']:.0%} average similarity to the current one.")


def _fallback_challenger(failed: dict, verdict: str) -> str:
    if failed["count"] == 0:
        return "No conflicting historical evidence is on record, but the sample size is still limited."
    ids = ", ".join(c["incident_id"] for c in failed["cases"][:3])
    return (f"{failed['count']} similar-looking past incident(s) ({ids}) did NOT resolve with this fix - "
           f"the resemblance may not hold for the true underlying cause here.")


@dataclass
class CourtroomResult:
    convened: bool
    advocate_text: str
    challenger_text: str
    advocate_used_llm: bool
    challenger_used_llm: bool
    evidence_strength: str
    historical_support: str
    conflicting_evidence: str
    base_trust: float
    trust_adjustment: float
    final_trust: float
    advocate_model: str
    challenger_model: str


def assess(risk_tier: str, verdict: str, trust: float, passed: dict, failed: dict) -> dict:
    """Pure code - the Courtroom Assessment labels and the trust adjustment. No LLM
    input of any kind. `passed`/`failed` are FixEvidence.passed/.failed as dicts."""
    evidence_strength = "HIGH" if (passed["label"] == "high" or failed["label"] == "high") else "LOW"
    if verdict == "agree_trust":
        historical_support = "STRONG"
    elif passed["count"] > 0:
        historical_support = "MODERATE"
    else:
        historical_support = "WEAK"
    if verdict == "conflict":
        conflicting = "HIGH"
    elif failed["count"] > 0:
        conflicting = "MODERATE"
    else:
        conflicting = "LOW"

    # Small, bounded, code-computed nudge from the real failed-side evidence relative to
    # the passed side - more/stronger conflicting cases pull trust down further, capped.
    if passed["sum_sim"] + failed["sum_sim"] > 0:
        raw = failed["sum_sim"] / (passed["sum_sim"] + failed["sum_sim"])
    else:
        raw = 0.0
    adjustment = -round(min(MAX_ADJUSTMENT, raw * MAX_ADJUSTMENT * 1.5), 4)
    final_trust = round(max(0.0, min(1.0, trust + adjustment)), 4)

    return {
        "evidence_strength": evidence_strength, "historical_support": historical_support,
        "conflicting_evidence": conflicting, "base_trust": round(trust, 4),
        "trust_adjustment": adjustment, "final_trust": final_trust,
    }


def convene(fix: str, risk_tier: str, verdict: str, trust: float, passed: dict, failed: dict) -> CourtroomResult:
    summary = _evidence_summary(fix, risk_tier, verdict, trust, passed, failed)
    adv_key, adv_model = llm_client.advocate_config()
    chl_key, chl_model = llm_client.challenger_config()

    try:
        advocate_text = llm_client.call(ADVOCATE_SYSTEM, summary, api_key=adv_key, model=adv_model)
        advocate_used_llm = True
    except llm_client.CourtroomLLMError as e:
        log.warning("Advocate call failed, using fallback: %s", e)
        advocate_text = _fallback_advocate(passed, verdict)
        advocate_used_llm = False

    try:
        challenger_text = llm_client.call(CHALLENGER_SYSTEM, summary, api_key=chl_key, model=chl_model)
        challenger_used_llm = True
    except llm_client.CourtroomLLMError as e:
        log.warning("Challenger call failed, using fallback: %s", e)
        challenger_text = _fallback_challenger(failed, verdict)
        challenger_used_llm = False

    a = assess(risk_tier, verdict, trust, passed, failed)
    return CourtroomResult(
        convened=True, advocate_text=advocate_text, challenger_text=challenger_text,
        advocate_used_llm=advocate_used_llm, challenger_used_llm=challenger_used_llm,
        advocate_model=adv_model, challenger_model=chl_model, **a,
    )
