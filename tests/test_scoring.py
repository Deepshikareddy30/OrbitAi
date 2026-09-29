"""Milestone 4 tests: similarity, two-sided evidence, verdict table, trust score,
ranking (SPEC S5.3-S5.4). Uses small synthetic fixtures so the math is tested directly,
independent of whatever thresholds get tuned into config.yaml.
"""

import math

import pytest

from engine import features as F
from engine.scoring import (
    age_days, cap_near_duplicates, rank_fixes, recency, score_fix, similarity, weighted_match,
)


def _incident(iid, ts, service="svc-a", env="prod", sig="oom", p99=1000, err=0.05, cpu=0.5, mem=0.5,
             changes=None, factors=None, attempts=None):
    return {
        "id": iid, "timestamp": ts, "service": service, "environment": env, "error_signature": sig,
        "symptoms": {"p99_ms": p99, "error_rate": err, "cpu": cpu, "mem": mem},
        "changes_before": changes or [], "contributing_factors": factors or [], "attempts": attempts or [],
        "slack_thread": [], "postmortem_note": "", "split": "train",
    }


def _attempt(fix, outcome, verified=True, ttr=5):
    return {"fix": fix, "outcome": outcome, "verified": verified, "time_to_recover_min": ttr,
           "recurred_within_24h": False, "human_override": False, "override_reason": None}


class FakeWeightsVersion:
    """Minimal stand-in for engine.weights.WeightsVersion, one fix, uniform importance."""
    def __init__(self, fix="restart_service", n_dims=None):
        self.version = "vfake"
        self.bands = F.fit_bands([_incident("x", "2026-01-01T00:00:00Z")]).to_dict()
        u = 1.0 / len(F.GROUPS)
        self.per_fix = {fix: _FW({g: u for g in F.GROUPS})}


class _FW:
    def __init__(self, group_importance):
        self.group_importance = group_importance


# -- recency / weighted match -------------------------------------------------

def test_recency_decays_with_age():
    assert recency(0, 90) == 1.0
    assert recency(90, 90) == pytest.approx(math.exp(-1))
    assert recency(90, 90) < recency(30, 90)


def test_weighted_match_identical_incidents_is_one():
    bands = F.fit_bands([_incident("x", "2026-01-01T00:00:00Z", p99=1000)] * 3)
    inc = _incident("a", "2026-01-01T00:00:00Z", factors=["recent_deploy"], changes=[{"type": "deploy", "detail": "v1", "minutes_before": 5}])
    g = F.feature_groups(inc, bands)
    importance = {group: 1.0 / len(F.GROUPS) for group in F.GROUPS}
    assert weighted_match(g, g, importance) == pytest.approx(1.0)


def test_weighted_match_zero_when_nothing_matches():
    bands = F.fit_bands([_incident("x", "2026-01-01T00:00:00Z")] * 3)
    a = F.feature_groups(_incident("a", "2026-01-01T00:00:00Z", service="svc-a", sig="oom"), bands)
    b = F.feature_groups(_incident("b", "2026-01-01T00:00:00Z", service="svc-z", sig="disk"), bands)
    importance = {"service": 0.5, "error_signature": 0.5}
    assert weighted_match(a, b, importance) == pytest.approx(0.0)


def test_similarity_combines_recency_and_match():
    bands = F.fit_bands([_incident("x", "2026-01-01T00:00:00Z")] * 3)
    present = _incident("p", "2026-04-01T00:00:00Z")
    past = _incident("c", "2026-01-01T00:00:00Z")  # 90 days earlier, identical features
    pg, cg = F.feature_groups(present, bands), F.feature_groups(past, bands)
    importance = {g: 1.0 / len(F.GROUPS) for g in F.GROUPS}
    sim = similarity(present, past, pg, cg, importance, tau_days=90)
    assert sim == pytest.approx(math.exp(-1), abs=1e-6)  # perfect match * recency(90,90)


# -- near-duplicate cap --------------------------------------------------

def test_cap_near_duplicates_keeps_highest_sim_per_cluster():
    key = ("svc-a", "oom", frozenset())
    cases = [{"cluster_key": key, "sim": s, "incident_id": f"c{i}"} for i, s in enumerate([0.9, 0.8, 0.7, 0.6, 0.5])]
    capped = cap_near_duplicates(cases, cap=3)
    assert len(capped) == 3
    assert [c["sim"] for c in capped] == [0.9, 0.8, 0.7]


def test_cap_near_duplicates_different_clusters_not_capped_together():
    key_a = ("svc-a", "oom", frozenset())
    key_b = ("svc-b", "oom", frozenset())
    cases = [{"cluster_key": key_a, "sim": 0.9, "incident_id": "a"},
            {"cluster_key": key_a, "sim": 0.8, "incident_id": "b"},
            {"cluster_key": key_b, "sim": 0.7, "incident_id": "c"}]
    capped = cap_near_duplicates(cases, cap=1)
    assert len(capped) == 2  # one kept per cluster


# -- verdict table (SPEC S5.4) ------------------------------------------------

@pytest.mark.parametrize("n_passed,n_failed,expected", [
    (6, 0, "agree_trust"),
    (0, 6, "agree_dont_trust"),
    (6, 6, "conflict"),
    (0, 0, "no_evidence"),
])
def test_verdict_table(n_passed, n_failed, expected):
    """Build a same-day, identical-feature present incident against many passed/failed
    verified attempts of one fix, on a threshold-agnostic config (tau_sim=0, hi=0.5, n_min=2)
    so this test doesn't depend on the tuned config.yaml values."""
    cfg = {"tau_sim": 0.0, "hi": 0.5, "n_min": 2, "top_k": 5, "tau_days": 90,
          "near_duplicate_cap": 100, "risk_mult": {"low": 1.0}}
    present = _incident("present", "2026-01-01T00:00:00Z")
    candidates = []
    for i in range(n_passed):
        candidates.append(_incident(f"pass{i}", "2026-01-01T00:00:00Z",
                                    attempts=[_attempt("restart_service", "resolved")]))
    for i in range(n_failed):
        candidates.append(_incident(f"fail{i}", "2026-01-01T00:00:00Z",
                                    attempts=[_attempt("restart_service", "failed")]))
    wv = FakeWeightsVersion()
    present_groups = F.feature_groups(present, F.Bands.from_dict(wv.bands))
    fe = score_fix("restart_service", "low", present, present_groups, candidates, wv, cfg)
    assert fe.verdict == expected


def test_unverified_attempts_excluded_from_evidence():
    cfg = {"tau_sim": 0.0, "hi": 0.5, "n_min": 1, "top_k": 5, "tau_days": 90,
          "near_duplicate_cap": 100, "risk_mult": {"low": 1.0}}
    present = _incident("present", "2026-01-01T00:00:00Z")
    candidates = [_incident("c1", "2026-01-01T00:00:00Z",
                            attempts=[_attempt("restart_service", "resolved", verified=False)])]
    wv = FakeWeightsVersion()
    present_groups = F.feature_groups(present, F.Bands.from_dict(wv.bands))
    fe = score_fix("restart_service", "low", present, present_groups, candidates, wv, cfg)
    assert fe.passed.count == 0
    assert fe.verdict == "no_evidence"


def test_trust_score_thin_evidence_stays_near_half():
    """Bayesian smoothing (SPEC S5.4): with zero evidence, T == 0.5 exactly."""
    cfg = {"tau_sim": 0.0, "hi": 0.5, "n_min": 5, "top_k": 5, "tau_days": 90,
          "near_duplicate_cap": 100, "risk_mult": {"low": 1.0}}
    present = _incident("present", "2026-01-01T00:00:00Z")
    wv = FakeWeightsVersion()
    present_groups = F.feature_groups(present, F.Bands.from_dict(wv.bands))
    fe = score_fix("restart_service", "low", present, present_groups, [], wv, cfg)
    assert fe.trust == pytest.approx(0.5)


def test_trust_score_higher_risk_penalizes_failures_more():
    cfg = {"tau_sim": 0.0, "hi": 0.9, "n_min": 99, "top_k": 5, "tau_days": 90,
          "near_duplicate_cap": 100, "risk_mult": {"low": 1.0, "high": 2.0}}
    present = _incident("present", "2026-01-01T00:00:00Z")
    candidates = [_incident("f1", "2026-01-01T00:00:00Z", attempts=[_attempt("x", "failed")])]
    wv = FakeWeightsVersion(fix="x")
    present_groups = F.feature_groups(present, F.Bands.from_dict(wv.bands))
    t_low = score_fix("x", "low", present, present_groups, candidates, wv, cfg).trust
    t_high = score_fix("x", "high", present, present_groups, candidates, wv, cfg).trust
    assert t_high < t_low


def test_rank_fixes_orders_by_trust_then_risk(monkeypatch):
    cfg = {"tau_sim": 0.0, "hi": 0.5, "n_min": 1, "top_k": 5, "tau_days": 90,
          "near_duplicate_cap": 100, "risk_mult": {"low": 1.0, "medium": 1.0}}
    present = _incident("present", "2026-01-01T00:00:00Z")
    candidates = [
        _incident("good", "2026-01-01T00:00:00Z", attempts=[_attempt("fix_low", "resolved")] * 3),
        _incident("bad", "2026-01-01T00:00:00Z", attempts=[_attempt("fix_med", "failed")] * 3),
    ]

    class WV(FakeWeightsVersion):
        def __init__(self):
            u = 1.0 / len(F.GROUPS)
            self.version = "vfake"
            self.bands = F.fit_bands([present]).to_dict()
            self.per_fix = {"fix_low": _FW({g: u for g in F.GROUPS}),
                            "fix_med": _FW({g: u for g in F.GROUPS})}

    fixes_catalog = [{"fix": "fix_low", "risk_tier": "low"}, {"fix": "fix_med", "risk_tier": "medium"}]
    ranked = rank_fixes(present, candidates, fixes_catalog, WV(), cfg)
    assert [fe.fix for fe in ranked] == ["fix_low", "fix_med"]
    assert ranked[0].trust > ranked[1].trust


def test_rank_fixes_verdict_priority_prefers_real_evidence_over_thin_higher_trust():
    """A fix with 1 thin all-pass case (no_evidence, below n_min) can have higher raw
    Bayesian-smoothed T than a fix with substantial mixed real evidence (agree_trust).
    verdict_priority=True must rank the real-evidence fix first anyway; the default
    (False) must be completely unaffected (every already-verified caller's numbers)."""
    cfg = {"tau_sim": 0.0, "hi": 0.5, "n_min": 3, "top_k": 5, "tau_days": 90,
          "near_duplicate_cap": 100, "risk_mult": {"low": 1.0}}
    present = _incident("present", "2026-01-01T00:00:00Z")
    candidates = (
        [_incident(f"thin{i}", "2026-01-01T00:00:00Z", attempts=[_attempt("thin_fix", "resolved")])
        for i in range(1)]
        + [_incident(f"real{i}", "2026-01-01T00:00:00Z", attempts=[_attempt("real_fix", "resolved")])
          for i in range(4)]
        + [_incident(f"realfail{i}", "2026-01-01T00:00:00Z", attempts=[_attempt("real_fix", "failed")])
          for i in range(2)]
    )
    wv = FakeWeightsVersion(fix="thin_fix")
    u = 1.0 / len(F.GROUPS)
    wv.per_fix["real_fix"] = _FW({g: u for g in F.GROUPS})
    fixes_catalog = [{"fix": "thin_fix", "risk_tier": "low"}, {"fix": "real_fix", "risk_tier": "low"}]

    default_order = [fe.fix for fe in rank_fixes(present, candidates, fixes_catalog, wv, cfg)]
    assert default_order[0] == "thin_fix"  # raw T favors the thin, unproven fix

    priority_order = rank_fixes(present, candidates, fixes_catalog, wv, cfg, verdict_priority=True)
    assert priority_order[0].fix == "real_fix"
    assert priority_order[0].verdict == "agree_trust"
    assert priority_order[1].verdict == "no_evidence"
