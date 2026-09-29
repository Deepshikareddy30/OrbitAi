"""Scoring against hidden ground truth (SPEC S10.2). Only this package (and generator/,
simworld/) may read hidden/ - see tests/test_hidden_leak.py.
"""

import json
from pathlib import Path


def load_p_success_table(repo_root: Path) -> dict[str, dict[str, float]]:
    """incident_id -> {fix: p_success}, covers train/held_out (root_causes.json/
    true_cause_weights.json) and demo (demo_expected.json)."""
    weights = json.loads((repo_root / "hidden" / "true_cause_weights.json").read_text())["incidents"]
    table = {iid: {fix: v["p_success"] for fix, v in breakdown.items()} for iid, breakdown in weights.items()}
    demo = json.loads((repo_root / "hidden" / "demo_expected.json").read_text())
    for iid, d in demo.items():
        table[iid] = d["p_success"]
    return table


def score_recommendation(incident_id: str, chosen_fix: str, p_table: dict[str, dict[str, float]]) -> dict:
    """SPEC S10.2: p_success, is_best (ties count as best), regret."""
    p_by_fix = p_table[incident_id]
    p = p_by_fix[chosen_fix]
    best = max(p_by_fix.values())
    return {"fix": chosen_fix, "p_success": round(p, 4), "is_best": p >= best - 1e-9,
           "regret": round(best - p, 4)}


def load_root_causes(repo_root: Path) -> dict[str, dict]:
    return json.loads((repo_root / "hidden" / "root_causes.json").read_text())


def load_true_cause_weights(repo_root: Path) -> dict:
    return json.loads((repo_root / "hidden" / "true_cause_weights.json").read_text())
