"""Milestone 6 tests: feedback loop - simulated outcome, retain, refit, poisoning guard
(SPEC S7). Includes the required poisoning demo: a fake 'always works' claim from an
unauthorized writer / unverified outcome must be stored-but-blocked, never used in math.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from feedback.loop import apply_outcome
from generator import REPO_ROOT
from generator.executor import execute_fix
from memory.fake_store import InMemoryStore
from memory.loader import retain_all_train

BANK = "test-bank"


@pytest.fixture(scope="module")
def incidents():
    return json.loads((REPO_ROOT / "data" / "incidents.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fix_names():
    return [f["fix"] for f in json.loads((REPO_ROOT / "data" / "fixes.json").read_text(encoding="utf-8"))]


@pytest.fixture(scope="module")
def engine_cfg():
    return yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["engine"]


@pytest.fixture(scope="module")
def generator_cfg():
    from generator import load_config
    return load_config()


def _demo_incident():
    """A fresh incident not already in incidents.json, with no attempts yet."""
    return {
        "id": "INC-FEEDBACK-TEST", "timestamp": "2026-09-10T00:00:00Z", "service": "billing-service",
        "environment": "prod", "error_signature": "timeout_upstream_db",
        "symptoms": {"p99_ms": 4200, "error_rate": 0.07, "cpu": 0.6, "mem": 0.5},
        "changes_before": [], "slack_thread": ["paging billing-service"], "attempts": [],
        "contributing_factors": ["connection_pool_low"], "postmortem_note": None, "split": "demo",
    }


# -- executor (generator-side, hidden-reading) --------------------------------

def test_execute_fix_returns_no_hidden_fields(generator_cfg):
    rng = np.random.default_rng(1)
    attempt, hidden = execute_fix("memory_leak", {"resource_limit_low"}, [], "restart_service",
                                  generator_cfg, rng)
    assert set(attempt) == {"fix", "outcome", "time_to_recover_min", "recurred_within_24h",
                            "verified", "human_override", "override_reason"}
    assert attempt["outcome"] in {"resolved", "failed", "recurred"}
    assert "root_cause" not in attempt and "p_success" not in attempt
    assert hidden["fix"] == "restart_service"  # hidden dict is for the caller's own debugging only


def test_execute_fix_is_reproducible_given_same_rng_state(generator_cfg):
    a1, _ = execute_fix("memory_leak", {"resource_limit_low"}, [], "restart_service",
                        generator_cfg, np.random.default_rng(42))
    a2, _ = execute_fix("memory_leak", {"resource_limit_low"}, [], "restart_service",
                        generator_cfg, np.random.default_rng(42))
    assert a1 == a2


# -- feedback loop: acceptance path --------------------------------------------

def test_verified_authorized_outcome_is_accepted_and_refits(incidents, fix_names, engine_cfg, tmp_path):
    store = InMemoryStore()
    working_set = [dict(i) for i in incidents]  # shallow copy list, incidents untouched
    inc = _demo_incident()
    attempt = {"fix": "raise_resource_limits", "outcome": "resolved", "time_to_recover_min": 9,
              "recurred_within_24h": False, "verified": True, "human_override": False, "override_reason": None}

    result = apply_outcome(inc, attempt, writer="system", authorized=True, store=store, bank_id=BANK,
                           incidents=working_set + [inc], fixes=fix_names, cfg=engine_cfg, weights_root=tmp_path)

    assert result.accepted
    assert result.weights_version == "v1"
    assert inc["split"] == "train"  # promoted into history
    assert (tmp_path / "weights" / "weights_v1.json").exists()
    assert any(e["event"] == "memory_retained" for e in result.audit_events)
    assert any(e["event"] == "weights_refit" for e in result.audit_events)


def test_accepted_outcome_is_retained_into_the_store(incidents, fix_names, engine_cfg, tmp_path):
    store = InMemoryStore()
    inc = _demo_incident()
    attempt = {"fix": "raise_resource_limits", "outcome": "resolved", "time_to_recover_min": 9,
              "recurred_within_24h": False, "verified": True, "human_override": False, "override_reason": None}
    apply_outcome(inc, attempt, writer="system", authorized=True, store=store, bank_id=BANK,
                 incidents=[dict(i) for i in incidents] + [inc], fixes=fix_names, cfg=engine_cfg,
                 weights_root=tmp_path, refit=False)
    hits = store.recall(BANK, "billing-service timeout_upstream_db raise_resource_limits")
    assert len(hits) == 1
    assert "verified:true" in hits[0].tags


# -- poisoning guard (SPEC S7: 'must exist and be demoable') --------------------

def test_poisoning_unverified_claim_is_stored_but_blocked(incidents, fix_names, engine_cfg, tmp_path):
    """A fake case claiming a risky fix 'always works', but with verified=False."""
    store = InMemoryStore()
    inc = _demo_incident()
    poisoned = {"fix": "db_failover", "outcome": "resolved", "time_to_recover_min": 1,
               "recurred_within_24h": False, "verified": False, "human_override": False, "override_reason": None}

    result = apply_outcome(inc, poisoned, writer="anonymous-script", authorized=True, store=store,
                           bank_id=BANK, incidents=[dict(i) for i in incidents] + [inc], fixes=fix_names,
                           cfg=engine_cfg, weights_root=tmp_path, refit=False)

    assert not result.accepted
    assert "unverified" in result.reason
    assert inc["split"] == "demo"  # NOT promoted to train
    # still stored (audit trail honesty) ...
    hits = store.recall(BANK, "billing-service db_failover")
    assert len(hits) == 1
    assert "verified:false" in hits[0].tags
    # ... but flagged blocked
    assert any(e["event"] == "memory_write_blocked" for e in result.audit_events)


def test_poisoning_unauthorized_writer_is_stored_but_blocked(incidents, fix_names, engine_cfg, tmp_path):
    """Same claim, this time verified=True but from an unauthorized writer."""
    store = InMemoryStore()
    inc = _demo_incident()
    poisoned = {"fix": "db_failover", "outcome": "resolved", "time_to_recover_min": 1,
               "recurred_within_24h": False, "verified": True, "human_override": False, "override_reason": None}

    result = apply_outcome(inc, poisoned, writer="unverified-external-tool", authorized=False, store=store,
                           bank_id=BANK, incidents=[dict(i) for i in incidents] + [inc], fixes=fix_names,
                           cfg=engine_cfg, weights_root=tmp_path, refit=False)

    assert not result.accepted
    assert "unauthorized" in result.reason
    assert any(e["event"] == "memory_write_blocked" for e in result.audit_events)


def test_poisoned_case_never_moves_the_trust_score(incidents, fix_names, engine_cfg, tmp_path):
    """The actual math-level guarantee: fitting weights with vs. without the poisoned
    claim in the incident list produces identical weights, because it's excluded from
    the logistic regression entirely (not just down-weighted)."""
    from engine.weights import fit_weights

    clean = [dict(i) for i in incidents]
    inc = _demo_incident()
    inc["attempts"] = [{"fix": "db_failover", "outcome": "resolved", "time_to_recover_min": 1,
                        "recurred_within_24h": False, "verified": False,
                        "human_override": False, "override_reason": None}]
    inc["split"] = "train"  # even if someone maliciously forced this into train...
    poisoned_set = clean + [inc]

    wv_clean = fit_weights(clean, fix_names, engine_cfg, "vclean")
    wv_poisoned = fit_weights(poisoned_set, fix_names, engine_cfg, "vpoisoned")
    assert wv_clean.per_fix["db_failover"].importance == wv_poisoned.per_fix["db_failover"].importance
    assert wv_clean.per_fix["db_failover"].n_train == wv_poisoned.per_fix["db_failover"].n_train
