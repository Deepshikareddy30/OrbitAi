"""Joins Hindsight recall results back to structured incident records by incident_id
(SPEC S2: 'Join Hindsight results to structured records by incident_id'; S4: recall,
take top N, join, hand to the engine).

This is the only place that talks to both memory/ (Hindsight) and engine/ (structured
records) - engine/ itself never imports memory/, keeping the math independently testable.
"""

import logging

from memory.base import MemoryStore
from memory.text import build_recall_query

log = logging.getLogger("engine.recall_bridge")


def _incident_id_from_hit(hit) -> str | None:
    """RecallHit.metadata carries incident_id (memory/text.py); fall back to parsing the
    document_id, which we write as '<incident_id>#<fix>' (memory/loader.py)."""
    iid = hit.metadata.get("incident_id") if hit.metadata else None
    if iid:
        return iid
    if hit.document_id and "#" in hit.document_id:
        return hit.document_id.split("#", 1)[0]
    return None


def recall_candidates(store: MemoryStore, bank_id: str, present: dict,
                      incidents_by_id: dict[str, dict], top_n: int = 30) -> list[dict]:
    """Recall similar past incidents for `present` and return their full structured
    records (deduplicated, most-relevant-first, missing/unknown ids skipped and logged).
    """
    query = build_recall_query(present)
    hits = store.recall(bank_id, query, top_n=top_n)

    seen: set[str] = set()
    candidates: list[dict] = []
    for hit in hits:
        iid = _incident_id_from_hit(hit)
        if not iid or iid in seen:
            continue
        seen.add(iid)
        record = incidents_by_id.get(iid)
        if record is None:
            log.warning("Recall hit referenced unknown incident_id %r (bank=%s)", iid, bank_id)
            continue
        candidates.append(record)
    return candidates


def index_by_id(incidents: list[dict]) -> dict[str, dict]:
    return {i["id"]: i for i in incidents}
