"""Live integration smoke test against real Hindsight Cloud. Skipped unless
HINDSIGHT_API_KEY is set - see docs/DECISIONS.md MEM1 (we don't yet have credentials).

Run manually once you have a key:
    HINDSIGHT_API_KEY=... HINDSIGHT_BASE_URL=... python -m pytest tests/test_hindsight_store.py -v
"""

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HINDSIGHT_API_KEY"),
    reason="HINDSIGHT_API_KEY not set - live Hindsight integration not configured yet",
)


@pytest.fixture(scope="module")
def store():
    from memory.hindsight_store import HindsightMemoryStore
    return HindsightMemoryStore(
        base_url=os.environ.get("HINDSIGHT_BASE_URL"),
        api_key=os.environ["HINDSIGHT_API_KEY"],
    )


def test_retain_recall_reflect_roundtrip(store):
    from memory.base import RetainItem

    bank_id = f"trustlens-smoketest-{int(time.time())}"
    try:
        store.retain(bank_id, RetainItem(
            content="[INC-TEST] billing-service/prod: timeout_upstream_db. Tried restart_service: failed.",
            tags=["service:billing-service", "fix:restart_service", "outcome:failed"],
        ))
        hits = store.recall(bank_id, "billing-service timeout_upstream_db restart_service")
        assert len(hits) >= 1

        result = store.reflect(bank_id, "What fixes were tried on billing-service?")
        assert isinstance(result.text, str) and result.text
    finally:
        store.reset(bank_id)
