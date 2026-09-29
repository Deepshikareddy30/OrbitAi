"""Milestone 8 tests: eval aggregates and truth-scoring math (fast, synthetic rows -
the full `python -m eval.run` replay is a slow (~60-90s) manual/CI-optional step,
verified separately - see docs/DECISIONS.md EVAL3)."""

import json

import pytest

from eval.aggregates import _auc, _brier, _calibration_table, _cumulative, _pearson, _rolling
from eval.truth import load_p_success_table, score_recommendation
from generator import REPO_ROOT


def test_rolling_and_cumulative_are_simple_means():
    values = [0.0, 1.0, 0.5, 1.0]
    assert _cumulative(values) == [0.0, 0.5, 0.5, round(2.5 / 4, 4)]
    assert _rolling(values, window=2) == [0.0, 0.5, 0.75, 0.75]


def test_auc_perfect_separation_is_one():
    scores = [0.9, 0.8, 0.2, 0.1]
    labels = [1, 1, 0, 0]
    assert _auc(scores, labels) == 1.0


def test_auc_random_is_near_half():
    scores = [0.5, 0.5, 0.5, 0.5]
    labels = [1, 0, 1, 0]
    assert _auc(scores, labels) == 0.5


def test_auc_none_when_only_one_class():
    assert _auc([0.9, 0.1], [1, 1]) is None


def test_brier_zero_for_perfect_predictions():
    assert _brier([1.0, 0.0], [1, 0]) == 0.0


def test_brier_worst_case():
    assert _brier([1.0, 0.0], [0, 1]) == 1.0


def test_calibration_table_bins_and_counts():
    scores = [0.05, 0.15, 0.85, 0.95]
    labels = [0, 1, 1, 1]
    table = _calibration_table(scores, labels, n_bins=5)
    assert sum(row["n"] for row in table) == 4


def test_pearson_perfect_positive_correlation():
    assert _pearson([1, 2, 3], [2, 4, 6]) == 1.0


def test_pearson_perfect_negative_correlation():
    assert _pearson([1, 2, 3], [-1, -2, -3]) == -1.0


def test_pearson_none_for_constant_input():
    assert _pearson([1, 1, 1], [1, 2, 3]) is None


# -- truth.py: against the real generated hidden data --------------------------

@pytest.fixture(scope="module")
def p_table():
    return load_p_success_table(REPO_ROOT)


def test_p_success_table_covers_all_incidents(p_table):
    incidents = json.loads((REPO_ROOT / "data" / "incidents.json").read_text())
    demo = json.loads((REPO_ROOT / "data" / "demo_incidents.json").read_text())
    for inc in incidents + demo:
        assert inc["id"] in p_table
        assert set(p_table[inc["id"]]) >= {"restart_service", "db_failover"}


def test_score_recommendation_best_fix_is_best(p_table):
    iid = next(iter(p_table))
    best_fix = max(p_table[iid], key=p_table[iid].get)
    result = score_recommendation(iid, best_fix, p_table)
    assert result["is_best"]
    assert result["regret"] == 0.0


def test_score_recommendation_worst_fix_has_positive_regret(p_table):
    iid = next(iter(p_table))
    worst_fix = min(p_table[iid], key=p_table[iid].get)
    best_fix = max(p_table[iid], key=p_table[iid].get)
    if worst_fix == best_fix:
        pytest.skip("degenerate incident where every fix ties")
    result = score_recommendation(iid, worst_fix, p_table)
    assert not result["is_best"]
    assert result["regret"] > 0
