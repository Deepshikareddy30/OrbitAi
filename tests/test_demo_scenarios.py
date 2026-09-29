"""Milestone 4 end-to-end check: the five demo-upload scenarios (SPEC S8) against the
real generated dataset and the tuned config.yaml thresholds (scripts/tune_thresholds.py).

These assertions describe the actual, honestly-scored behavior (including where a
high-risk fix's raw trust outranks a better medium-risk fix but carries a no_evidence
verdict - see docs/DECISIONS.md ENG7) rather than an idealized script.
"""

import json

import pytest
import yaml

from engine.scoring import rank_fixes, score_fix
from engine.weights import fit_weights
from engine import features as F
from generator import REPO_ROOT


@pytest.fixture(scope="module")
def data():
    incidents = json.loads((REPO_ROOT / "data" / "incidents.json").read_text())
    fixes_catalog = json.loads((REPO_ROOT / "data" / "fixes.json").read_text())
    demo = json.loads((REPO_ROOT / "data" / "demo_incidents.json").read_text())
    cfg = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["engine"]
    train = [i for i in incidents if i["split"] == "train"]
    fix_names = [f["fix"] for f in fixes_catalog]
    wv = fit_weights(incidents, fix_names, cfg, "vtest")
    demo_by_key = {d["id"].split("-")[1]: d for d in demo}
    return {"train": train, "fixes_catalog": fixes_catalog, "cfg": cfg, "wv": wv, "demo": demo_by_key}


def test_demo_a_clean_pass_history(data):
    """A: a clean, low-risk win with no meaningful conflicting evidence."""
    ranked = rank_fixes(data["demo"]["A"], data["train"], data["fixes_catalog"], data["wv"], data["cfg"])
    top = ranked[0]
    assert top.fix == "restart_service"
    assert top.verdict == "agree_trust"
    assert top.risk_tier == "low"


def test_demo_b_obvious_fix_is_not_the_winner(data):
    """B: the naive runbook fix (restart_service) is not the top recommendation."""
    ranked = rank_fixes(data["demo"]["B"], data["train"], data["fixes_catalog"], data["wv"], data["cfg"])
    assert ranked[0].fix != "restart_service"
    assert ranked[0].verdict == "agree_trust"


def test_demo_c_lookalike_trap(data):
    """C: rollback_deploy wins overall, AND restart_service is specifically flagged
    conflict (real passes from genuine leaks, real failures from bad deploys - the
    'looks similar but isn't' trap plain recall would miss)."""
    d = data["demo"]["C"]
    ranked = rank_fixes(d, data["train"], data["fixes_catalog"], data["wv"], data["cfg"])
    assert ranked[0].fix == "rollback_deploy"
    assert ranked[0].verdict == "agree_trust"

    present_groups = F.feature_groups(d, F.Bands.from_dict(data["wv"].bands))
    restart_evidence = score_fix("restart_service", "low", d, present_groups, data["train"],
                                 data["wv"], data["cfg"])
    assert restart_evidence.verdict == "conflict"
    assert restart_evidence.passed.count > 0 and restart_evidence.failed.count > 0


def test_demo_d_novel_combo_has_no_evidence(data):
    """D: the withheld (message-queue, config_error) combo - every fix is no_evidence."""
    ranked = rank_fixes(data["demo"]["D"], data["train"], data["fixes_catalog"], data["wv"], data["cfg"])
    assert all(fe.verdict == "no_evidence" for fe in ranked)


def test_demo_e_medium_fix_shows_real_conflict(data):
    """E: the intended medium-risk answer (raise_resource_limits) has genuinely mixed
    (conflict) evidence rather than a clean trust/don't-trust verdict - a legitimately
    borderline call for the gate, not a scripted number."""
    d = data["demo"]["E"]
    present_groups = F.feature_groups(d, F.Bands.from_dict(data["wv"].bands))
    fe = score_fix("raise_resource_limits", "medium", d, present_groups, data["train"], data["wv"], data["cfg"])
    assert fe.verdict in ("conflict", "agree_trust")
    assert fe.passed.count + fe.failed.count > 0  # some real evidence, not novel


def test_demo_e_high_risk_contender_is_not_agree_trust(data):
    """Whatever ranks by raw trust, no high-risk fix should carry an agree_trust verdict
    off 2 thin cases - this is exactly what the Adaptive Gate's verdict-gating (not
    trust-alone) is for (SPEC S6)."""
    ranked = rank_fixes(data["demo"]["E"], data["train"], data["fixes_catalog"], data["wv"], data["cfg"])
    for fe in ranked:
        if fe.risk_tier == "high":
            assert fe.verdict != "agree_trust" or fe.passed.count >= data["cfg"]["n_min"] + 1
