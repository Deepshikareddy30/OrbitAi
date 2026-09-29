"""Bulk-load training incidents into a MemoryStore (SPEC S4: 'retain each attempt
(only for split == train at startup; new verified outcomes later)').
"""

import logging

from .base import MemoryStore, RetainItem
from .text import build_attempt_metadata, build_attempt_tags, build_attempt_text

log = logging.getLogger("memory.loader")

BATCH_SIZE = 25


def retain_incident(incident: dict, *, writer: str = "system", authorized: bool = True) -> list[RetainItem]:
    """One RetainItem per attempt (SPEC S4)."""
    items = []
    for attempt in incident["attempts"]:
        items.append(RetainItem(
            content=build_attempt_text(incident, attempt),
            context="incident_response",
            timestamp=incident["timestamp"],
            document_id=f"{incident['id']}#{attempt['fix']}",
            tags=build_attempt_tags(incident, attempt, writer=writer, authorized=authorized),
            metadata=build_attempt_metadata(incident, attempt),
        ))
    return items


def retain_all_train(store: MemoryStore, bank_id: str, incidents: list[dict]) -> int:
    """Retain every training incident's attempts. Returns count of items retained."""
    pending: list[RetainItem] = []
    total = 0
    for inc in incidents:
        if inc["split"] != "train":
            continue
        pending.extend(retain_incident(inc))
        while len(pending) >= BATCH_SIZE:
            batch, pending = pending[:BATCH_SIZE], pending[BATCH_SIZE:]
            store.retain_batch(bank_id, batch)
            total += len(batch)
    if pending:
        store.retain_batch(bank_id, pending)
        total += len(pending)
    log.info("Retained %d attempt-memories into bank %s", total, bank_id)
    return total
