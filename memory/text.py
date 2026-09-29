"""Build the narrative text, tags and recall query for an incident/attempt (SPEC S4).

Deliberately never mentions the hidden root cause (see docs/DECISIONS.md G1) - only what
a real postmortem would actually know.
"""

from typing import Optional


def _changes_text(changes_before: list[dict]) -> str:
    if not changes_before:
        return "No changes before."
    parts = [f"{c['type'].replace('_', ' ')} {c['detail']} ({c['minutes_before']} min before)"
             for c in changes_before]
    return "Changes before: " + "; ".join(parts) + "."


def build_attempt_text(incident: dict, attempt: dict) -> str:
    """SPEC S4 example: '[INC-0042] billing-service/prod: timeout_upstream_db. Changes
    before: deploy v2.14.1 (25 min). Tried restart_service: failed. Postmortem: ... Slack: ...'
    """
    outcome = attempt["outcome"]
    if outcome == "resolved" and not attempt["verified"]:
        outcome_text = "marked resolved but NOT verified by metrics"
    elif outcome == "resolved":
        outcome_text = f"resolved in {attempt['time_to_recover_min']} min"
    elif outcome == "recurred":
        outcome_text = f"worked initially ({attempt['time_to_recover_min']} min) but recurred within 24h"
    else:
        outcome_text = "failed, no recovery"

    override = ""
    if attempt["human_override"]:
        override = f" (human override: {attempt['override_reason']})"

    slack = " ".join(incident["slack_thread"][:3])
    factors = ", ".join(incident["contributing_factors"]) or "none noted"

    return (
        f"[{incident['id']}] {incident['service']}/{incident['environment']}: "
        f"{incident['error_signature']}. {_changes_text(incident['changes_before'])} "
        f"Contributing factors noted: {factors}. "
        f"Tried {attempt['fix']}: {outcome_text}{override}. "
        f"Postmortem: {incident.get('postmortem_note') or 'n/a'}. Slack: {slack}"
    )


def build_attempt_tags(incident: dict, attempt: dict, *, writer: str = "system", authorized: bool = True) -> list[str]:
    """SPEC S4: incident_id, service, env, fix, outcome, verified, one tag per contributing factor."""
    tags = [
        f"incident_id:{incident['id']}",
        f"service:{incident['service']}",
        f"env:{incident['environment']}",
        f"signature:{incident['error_signature']}",
        f"fix:{attempt['fix']}",
        f"outcome:{attempt['outcome']}",
        f"verified:{str(attempt['verified']).lower()}",
        f"writer:{writer}",
        f"authorized:{str(authorized).lower()}",
    ]
    tags += [f"factor:{f}" for f in incident["contributing_factors"]]
    return tags


def build_attempt_metadata(incident: dict, attempt: dict) -> dict[str, str]:
    return {
        "incident_id": incident["id"],
        "service": incident["service"],
        "environment": incident["environment"],
        "error_signature": incident["error_signature"],
        "fix": attempt["fix"],
        "outcome": attempt["outcome"],
        "verified": str(attempt["verified"]),
        "time_to_recover_min": str(attempt["time_to_recover_min"]),
        "recurred_within_24h": str(attempt["recurred_within_24h"]),
    }


def build_recall_query(present: dict) -> str:
    """SPEC S4: 'query built from the present incident (service, error signature,
    changes before, symptom summary)'.
    """
    s = present["symptoms"]
    change_bits = ", ".join(
        f"{c['type'].replace('_', ' ')} {c['minutes_before']}m before" for c in present.get("changes_before", [])
    ) or "no recent changes"
    return (
        f"Incident on {present['service']} in {present['environment']}: {present['error_signature']}. "
        f"p99 {s['p99_ms']}ms, error rate {s['error_rate']:.1%}, cpu {s['cpu']:.0%}, mem {s['mem']:.0%}. "
        f"{change_bits}. What fixes were tried for similar incidents, and did they work?"
    )
