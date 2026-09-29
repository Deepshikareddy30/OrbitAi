"""apply_outcome(): the SPEC S7 feedback loop.

    1. Retain the attempt into Hindsight - always, regardless of verification.
    2. If verified AND the writer is authorized: mark it usable, flip the incident to
       'train' if it wasn't already, refit weights, save a new version, call reflect.
    3. Otherwise: it's stored (so the audit trail is honest) but excluded from the math
       and clearly flagged 'memory_write_blocked' (the poisoning guard, SPEC S4/S7).

Never marks success just because someone clicked "resolved" - that's `verified`, decided
upstream by whatever ran the metric check (generator.executor in the simulated world).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.weights import fit_and_save
from memory.base import MemoryStore, RetainItem
from memory.text import build_attempt_metadata, build_attempt_tags, build_attempt_text


@dataclass
class FeedbackResult:
    incident_id: str
    fix: str
    outcome: str
    time_to_recover_min: Optional[int]
    verified: bool
    recurred_within_24h: bool
    accepted: bool           # did this outcome update weights/memory-math
    reason: str
    weights_version: Optional[str] = None
    audit_events: list = field(default_factory=list)


def apply_outcome(incident: dict, attempt: dict, *, writer: str, authorized: bool,
                  store: MemoryStore, bank_id: str, incidents: list[dict], fixes: list[str],
                  cfg: dict, weights_root: Path, refit: bool = True) -> FeedbackResult:
    """Mutates `incident` (appends `attempt`, and on acceptance flips split to 'train' so
    it counts as history for the next fit). `incident` must already be present in
    `incidents` (by identity or by 'id') for the refit to see this new attempt.
    """
    incident.setdefault("attempts", []).append(attempt)
    events = []

    if not attempt["verified"]:
        accepted, reason = False, "rejected: unverified outcome (metric check did not confirm recovery)"
    elif not authorized:
        accepted, reason = False, f"rejected: unauthorized writer {writer!r}"
    else:
        accepted, reason = True, "accepted: verified outcome from an authorized writer"

    item = RetainItem(
        content=build_attempt_text(incident, attempt), context="incident_response",
        timestamp=incident["timestamp"],
        document_id=f"{incident['id']}#{attempt['fix']}#{len(incident['attempts'])}",
        tags=build_attempt_tags(incident, attempt, writer=writer, authorized=authorized),
        metadata=build_attempt_metadata(incident, attempt),
    )
    store.retain(bank_id, item)
    events.append({"event": "memory_retained", "incident_id": incident["id"], "fix": attempt["fix"],
                   "verified": attempt["verified"], "authorized": authorized})

    weights_version = None
    if accepted:
        if incident.get("split") != "train":
            incident["split"] = "train"  # a resolved+verified incident becomes future history
        if refit:
            wv = fit_and_save(incidents, fixes, cfg, weights_root)
            weights_version = wv.version
            events.append({"event": "weights_refit", "version": wv.version})
            try:
                reflect_result = store.reflect(
                    bank_id, f"What changed for {attempt['fix']} on {incident['service']}?")
                events.append({"event": "reflect_run", "text": reflect_result.text})
            except Exception as e:  # noqa: BLE001 - reflect is best-effort, math never depends on it
                events.append({"event": "reflect_run", "error": str(e)})
    else:
        events.append({"event": "memory_write_blocked", "incident_id": incident["id"],
                       "fix": attempt["fix"], "reason": reason})

    return FeedbackResult(
        incident_id=incident["id"], fix=attempt["fix"], outcome=attempt["outcome"],
        time_to_recover_min=attempt["time_to_recover_min"], verified=attempt["verified"],
        recurred_within_24h=attempt["recurred_within_24h"], accepted=accepted, reason=reason,
        weights_version=weights_version, audit_events=events,
    )
