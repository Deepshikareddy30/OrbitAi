"""Milestone 5 tests: Adaptive Gate (SPEC S6) - a rule table, every tier and modifier."""

import pytest
import yaml

from engine.gate import LEVELS, break_glass, decide, escalate_on_timeout
from generator import REPO_ROOT


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load((REPO_ROOT / "gate_config.yaml").read_text())


# -- base table, one test per (risk tier x trusted/not) cell -----------------------

def test_low_risk_trusted_auto_runs(cfg):
    d = decide("restart_service", "low", "prod", "agree_trust", 0.85, cfg)
    assert d.action == "auto_run"
    assert d.notify == "on_call"


def test_low_risk_untrusted_needs_one_click(cfg):
    d = decide("restart_service", "low", "prod", "agree_trust", 0.50, cfg)  # below 0.70 threshold
    assert d.action == "one_click"


def test_medium_risk_trusted_one_click(cfg):
    d = decide("rollback_deploy", "medium", "prod", "agree_trust", 0.65, cfg)
    assert d.action == "one_click"
    assert d.notify == "on_call"


def test_medium_risk_untrusted_escalates_to_incident_commander(cfg):
    d = decide("rollback_deploy", "medium", "prod", "agree_trust", 0.40, cfg)  # below 0.60
    assert d.action == "escalate_ic"
    assert d.notify == "incident_commander"


def test_high_risk_trusted_still_requires_human_one_click(cfg):
    d = decide("db_failover", "high", "prod", "agree_trust", 0.90, cfg)
    assert d.action == "one_click"  # never auto-runs, even at very high trust
    assert d.notify == "on_call"


def test_high_risk_untrusted_two_person(cfg):
    d = decide("db_failover", "high", "prod", "agree_trust", 0.50, cfg)  # below 0.80
    assert d.action == "two_person"
    assert d.notify == "two_person"


def test_high_risk_never_auto_runs_regardless_of_trust(cfg):
    for trust in (0.0, 0.5, 0.8, 0.99, 1.0):
        d = decide("db_failover", "high", "prod", "agree_trust", trust, cfg)
        assert d.action != "auto_run"


# -- staging modifier: relaxes one level ------------------------------------------

def test_staging_relaxes_one_click_to_auto_run(cfg):
    d = decide("restart_service", "low", "staging", "agree_trust", 0.50, cfg)  # untrusted -> one_click in prod
    assert d.action == "auto_run"
    assert d.relaxed_for_staging


def test_staging_relaxes_two_person_to_escalate_ic(cfg):
    d = decide("db_failover", "high", "staging", "agree_trust", 0.50, cfg)  # two_person in prod
    assert d.action == "escalate_ic"
    assert d.relaxed_for_staging


def test_staging_does_not_relax_below_auto_run(cfg):
    d = decide("restart_service", "low", "staging", "agree_trust", 0.85, cfg)  # already auto_run
    assert d.action == "auto_run"
    assert not d.relaxed_for_staging


def test_prod_uses_table_as_written_no_relaxation(cfg):
    d = decide("restart_service", "low", "prod", "agree_trust", 0.50, cfg)
    assert d.action == "one_click"
    assert not d.relaxed_for_staging


# -- verdict floor: conflict/no_evidence force >= one_click, applied after staging --

def test_conflict_never_auto_runs_regardless_of_trust(cfg):
    """In prod the base table's own agree_trust check already prevents this (conflict
    never takes the if_trusted branch); the floor exists for the staging-relaxation
    case below, where relaxation alone could otherwise push action below one_click."""
    d = decide("restart_service", "low", "prod", "conflict", 0.90, cfg)
    assert d.action == "one_click"


def test_no_evidence_forces_one_click_even_in_staging(cfg):
    """Staging would relax an untrusted low-risk fix to auto_run; no_evidence must
    still floor it back up to one_click (floor applied after relaxation)."""
    d = decide("restart_service", "low", "staging", "no_evidence", 0.50, cfg)
    assert d.action == "one_click"
    assert d.floored_by_verdict


def test_floor_is_a_no_op_when_already_at_or_above_one_click(cfg):
    d = decide("db_failover", "high", "prod", "conflict", 0.50, cfg)  # already two_person
    assert d.action == "two_person"
    assert not d.floored_by_verdict


def test_agree_dont_trust_does_not_trigger_the_floor(cfg):
    """Floor is specifically for conflict/no_evidence, not every non-trusted verdict."""
    d = decide("restart_service", "low", "prod", "agree_dont_trust", 0.20, cfg)
    assert d.action == "one_click"  # from the base table's 'otherwise' branch, not the floor
    assert not d.floored_by_verdict


# -- timeout escalation -----------------------------------------------------------

def test_timeout_escalates_to_next_tier(cfg):
    d = decide("rollback_deploy", "medium", "prod", "agree_trust", 0.65, cfg)  # one_click, timeout 10min
    assert d.action == "one_click"
    escalated = escalate_on_timeout(d, elapsed_min=15)
    assert escalated.action == "escalate_ic"
    assert "escalated" in escalated.reason


def test_no_timeout_escalation_before_deadline(cfg):
    d = decide("rollback_deploy", "medium", "prod", "agree_trust", 0.65, cfg)
    unchanged = escalate_on_timeout(d, elapsed_min=5)
    assert unchanged.action == d.action


def test_timeout_escalation_caps_at_most_restrictive_tier(cfg):
    d = decide("db_failover", "high", "prod", "agree_trust", 0.50, cfg)  # two_person, no further tier
    escalated = escalate_on_timeout(d, elapsed_min=999)
    assert escalated.action == "two_person"  # already at LEVELS[-1], stays put


def test_auto_run_has_no_timeout_to_escalate():
    from engine.gate import GateDecision
    d = GateDecision(fix="x", risk_tier="low", environment="prod", verdict="agree_trust",
                     trust=0.9, action="auto_run", notify="on_call", reason="", timeout_min=None)
    assert escalate_on_timeout(d, elapsed_min=999).action == "auto_run"


# -- break glass -------------------------------------------------------------------

def test_break_glass_always_requires_post_incident_review():
    d = break_glass("db_failover", "high", "prod", actor="oncall-jane", reason="prod is down, no time")
    assert d.requires_post_incident_review
    assert d.action == "break_glass"
    assert "oncall-jane" in d.reason


# -- structural: level ordering sanity -----------------------------------------

def test_levels_are_strictly_ordered():
    assert LEVELS == ["auto_run", "one_click", "escalate_ic", "two_person"]
