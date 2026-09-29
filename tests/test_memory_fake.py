"""Milestone 2 unit tests against the in-memory fake (SPEC S1 allows this for tests only)."""

import json
from pathlib import Path

import pytest

from generator import REPO_ROOT
from memory.base import RetainItem
from memory.fake_store import InMemoryStore
from memory.loader import retain_all_train, retain_incident
from memory.text import build_attempt_tags, build_attempt_text, build_recall_query

BANK = "test-bank"


@pytest.fixture(scope="module")
def incidents():
    return json.loads((REPO_ROOT / "data" / "incidents.json").read_text(encoding="utf-8"))


def test_retain_and_recall_roundtrip():
    store = InMemoryStore()
    store.retain(BANK, RetainItem(content="billing-service prod timeout_upstream_db restart_service failed",
                                  tags=["service:billing-service"]))
    hits = store.recall(BANK, "billing-service timeout_upstream_db")
    assert len(hits) == 1
    assert "billing-service" in hits[0].text


def test_recall_respects_tag_filter():
    store = InMemoryStore()
    store.retain_batch(BANK, [
        RetainItem(content="auth-service memory leak restart_service resolved", tags=["service:auth-service"]),
        RetainItem(content="auth-service memory leak restart_service resolved", tags=["service:billing-service"]),
    ])
    hits = store.recall(BANK, "auth-service memory leak", tags=["service:auth-service"])
    assert len(hits) == 1


def test_reset_clears_bank():
    store = InMemoryStore()
    store.retain(BANK, RetainItem(content="something"))
    store.reset(BANK)
    assert store.recall(BANK, "something") == []


def test_build_attempt_text_never_names_root_cause():
    from generator import world as W
    fake_incident = {
        "id": "INC-0001", "service": "billing-service", "environment": "prod",
        "error_signature": "timeout_upstream_db", "changes_before": [],
        "contributing_factors": ["connection_pool_low"], "postmortem_note": "note", "slack_thread": ["line"],
    }
    fake_attempt = {"fix": "restart_service", "outcome": "failed", "time_to_recover_min": None,
                    "verified": True, "human_override": False, "override_reason": None,
                    "recurred_within_24h": False}
    text = build_attempt_text(fake_incident, fake_attempt)
    tags = build_attempt_tags(fake_incident, fake_attempt)
    for rc in W.ROOT_CAUSES:
        assert rc not in text
        assert not any(rc in t for t in tags)


def test_recall_query_mentions_key_fields():
    present = {"service": "billing-service", "environment": "prod", "error_signature": "timeout_upstream_db",
              "symptoms": {"p99_ms": 4200, "error_rate": 0.07, "cpu": 0.91, "mem": 0.62},
              "changes_before": [{"type": "deploy", "detail": "v2.14.1", "minutes_before": 25}]}
    q = build_recall_query(present)
    assert "billing-service" in q and "timeout_upstream_db" in q and "deploy" in q


def test_retain_incident_one_item_per_attempt(incidents):
    inc = next(i for i in incidents if len(i["attempts"]) >= 2)
    items = retain_incident(inc)
    assert len(items) == len(inc["attempts"])
    assert all(it.document_id.startswith(inc["id"]) for it in items)


def test_retain_all_train_only_retains_train_split(incidents):
    store = InMemoryStore()
    n = retain_all_train(store, BANK, incidents)
    expected = sum(len(i["attempts"]) for i in incidents if i["split"] == "train")
    assert n == expected
    assert n == len(store._banks[BANK])


def test_recall_similar_incidents_after_bulk_load(incidents):
    """Sanity check for milestone 2: recall on a real incident returns same-service hits."""
    store = InMemoryStore()
    retain_all_train(store, BANK, incidents)
    target = next(i for i in incidents if i["split"] == "held_out")
    hits = store.recall(BANK, build_recall_query(target), top_n=10)
    assert len(hits) > 0
