"""Aggregate metrics over the replay's per-incident rows (SPEC S10.3).

Reads hidden ground truth for weight_recovery only - everything else here operates on
the already-scored rows eval.run produced.
"""

import math
from pathlib import Path

from .truth import load_true_cause_weights


def _rolling(values: list[float], window: int) -> list[float]:
    return [round(sum(values[max(0, i - window + 1):i + 1]) / (i - max(0, i - window + 1) + 1), 4)
           for i in range(len(values))]


def _cumulative(values: list[float]) -> list[float]:
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        out.append(round(total / (i + 1), 4))
    return out


def _auc(scores: list[float], labels: list[int]) -> float | None:
    """Rank-based AUC (Mann-Whitney U), no sklearn dependency needed for this."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    wins = sum((s_p > s_n) + 0.5 * (s_p == s_n) for s_p in pos for s_n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def _brier(scores: list[float], labels: list[int]) -> float | None:
    if not scores:
        return None
    return round(sum((s - y) ** 2 for s, y in zip(scores, labels)) / len(scores), 4)


def _calibration_table(scores: list[float], labels: list[int], n_bins: int = 5) -> list[dict]:
    bins = [[] for _ in range(n_bins)]
    for s, y in zip(scores, labels):
        idx = min(n_bins - 1, int(s * n_bins))
        bins[idx].append((s, y))
    table = []
    for i, b in enumerate(bins):
        if not b:
            continue
        table.append({
            "bin": f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}", "n": len(b),
            "mean_predicted": round(sum(s for s, _ in b) / len(b), 4),
            "actual_rate": round(sum(y for _, y in b) / len(b), 4),
        })
    return table


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if va == 0 or vb == 0:
        return None
    return round(cov / (va * vb), 4)


# A handful of known hidden modifiers (factor -> fix -> true logit effect) to correlate
# against the learned, signed value-level coefficients - a concrete "did reflection
# recover real structure from noisy outcomes" check (SPEC S10.3 weight_recovery).
_KNOWN_MODIFIER_PAIRS = [
    ("recent_deploy", "restart_service"), ("recent_deploy", "rollback_deploy"),
    ("traffic_spike", "scale_out"), ("resource_limit_low", "raise_resource_limits"),
    ("connection_pool_low", "raise_resource_limits"), ("cache_cold", "clear_cache"),
    ("dependency_degraded", "toggle_feature_flag"), ("disk_usage_high", "drain_node"),
]


def _weight_recovery(repo_root: Path, weights_root: Path) -> dict:
    from engine.weights import load_latest

    wv = load_latest(weights_root)
    if wv is None:
        return {"correlation": None, "n_pairs": 0, "pairs": []}
    true_mods = load_true_cause_weights(repo_root)["modifiers"]
    learned, truth = [], []
    pairs = []
    for factor, fix in _KNOWN_MODIFIER_PAIRS:
        true_val = true_mods.get(factor, {}).get(fix)
        learned_val = wv.per_fix.get(fix, None)
        learned_coef = learned_val.local_coef.get(f"factors={factor}") if learned_val else None
        if true_val is None or learned_coef is None:
            continue
        learned.append(learned_coef)
        truth.append(true_val)
        pairs.append({"factor": factor, "fix": fix, "true": true_val, "learned": round(learned_coef, 3)})
    return {"correlation": _pearson(learned, truth), "n_pairs": len(pairs), "pairs": pairs}


def _lookalike_subset(rows: list[dict]) -> dict:
    """How each system does on the deliberately-overlapping mem_pressure_oom signature -
    the same trap structure demo scenario C exercises (SPEC S3.5, S10.3)."""
    subset = [r for r in rows if r.get("_signature") == "mem_pressure_oom"]
    if not subset:
        return {"n": 0}
    return {
        "n": len(subset),
        "baseline_best_fix_rate": round(sum(r["baseline"]["is_best"] for r in subset) / len(subset), 4),
        "trustlens_best_fix_rate": round(sum(r["trustlens"]["is_best"] for r in subset) / len(subset), 4),
        "trustlens_conflict_rate": round(
            sum(r["trustlens"]["verdict"] == "conflict" for r in subset) / len(subset), 4),
    }


def _learning_curve(incidents: list[dict], fixes_catalog: list[dict], engine_cfg: dict,
                    p_table: dict, sizes: list[int], sample_cap: int = 30) -> list[dict]:
    """Fit weights on increasingly large prefixes of train (oldest-first) and score the
    top pick against a capped sample of held_out, holding everything else fixed. Not the
    same incremental-learning run as the main replay (which also lets OrbitAI learn
    from held_out as it goes) - this isolates 'more starting history alone helps'."""
    from engine.recall_bridge import index_by_id, recall_candidates
    from engine.scoring import rank_fixes
    from engine.weights import fit_weights
    from memory.fake_store import InMemoryStore
    from memory.loader import retain_all_train

    train_all = sorted([i for i in incidents if i["split"] == "train"], key=lambda i: i["timestamp"])
    held_sample = [i for i in incidents if i["split"] == "held_out"][:sample_cap]
    fix_names = [f["fix"] for f in fixes_catalog]

    curve = []
    for n in sizes:
        tagged = [dict(i, split="train") for i in train_all[:n]] + \
                 [dict(i, split="held_out") for i in train_all[n:]]
        wv = fit_weights(tagged, fix_names, engine_cfg, f"vcurve{n}")
        store = InMemoryStore()
        retain_all_train(store, "curve", tagged)
        by_id = index_by_id(tagged)
        ps = []
        for inc in held_sample:
            cands = recall_candidates(store, "curve", inc, by_id, top_n=engine_cfg["recall_top_n"])
            ranked = rank_fixes(inc, cands, fixes_catalog, wv, engine_cfg) if wv.per_fix else []
            fix = ranked[0].fix if ranked else "restart_service"
            ps.append(p_table[inc["id"]][fix])
        curve.append({"n_train": n, "mean_p_success": round(sum(ps) / len(ps), 4) if ps else None,
                      "n_scored": len(ps)})
    return curve


def compute_aggregates(rows: list[dict], incidents: list[dict], repo_root: Path, engine_cfg: dict,
                       weights_root: Path | None = None, fixes_catalog: list[dict] | None = None,
                       p_table: dict | None = None) -> dict:
    if not rows:
        return {}
    b_p = [r["baseline"]["p_success"] for r in rows]
    t_p = [r["trustlens"]["p_success"] for r in rows]
    b_best = [r["baseline"]["is_best"] for r in rows]
    t_best = [r["trustlens"]["is_best"] for r in rows]
    b_regret = [r["baseline"]["regret"] for r in rows]
    t_regret = [r["trustlens"]["regret"] for r in rows]

    escalated = [r for r in rows if r["trustlens"]["verdict"] in ("conflict", "no_evidence")]
    non_escalated = [r for r in rows if r["trustlens"]["verdict"] not in ("conflict", "no_evidence")]
    escalation_rate = round(len(escalated) / len(rows), 4)
    accuracy_non_escalated = (round(sum(r["trustlens"]["is_best"] for r in non_escalated) / len(non_escalated), 4)
                              if non_escalated else None)

    T = [r["trustlens"]["T"] for r in rows]
    y = [1 if r["trustlens"]["sampled_outcome"] == "resolved" and r["trustlens"]["sampled_verified"] else 0
        for r in rows]

    result = {
        "rolling_p_success": {"window": 10, "baseline": _rolling(b_p, 10), "trustlens": _rolling(t_p, 10)},
        "cumulative_p_success": {"baseline": _cumulative(b_p), "trustlens": _cumulative(t_p)},
        "best_fix_rate": {"baseline": round(sum(b_best) / len(rows), 4),
                          "trustlens": round(sum(t_best) / len(rows), 4)},
        "mean_regret": {"baseline": round(sum(b_regret) / len(rows), 4),
                        "trustlens": round(sum(t_regret) / len(rows), 4)},
        "mean_p_success": {"baseline": round(sum(b_p) / len(rows), 4), "trustlens": round(sum(t_p) / len(rows), 4)},
        "escalation": {"rate": escalation_rate, "n_escalated": len(escalated),
                      "accuracy_on_non_escalated": accuracy_non_escalated},
        "calibration": _calibration_table(T, y),
        "brier": _brier(T, y),
        "auc": _auc(T, y),
        "lookalike_subset": _lookalike_subset(rows),
    }
    if weights_root:
        result["weight_recovery"] = _weight_recovery(repo_root, weights_root)
    if fixes_catalog and p_table:
        n_train = len([i for i in incidents if i["split"] == "train"])
        sizes = sorted({n for n in (50, 100, 150, 200, n_train) if 0 < n <= n_train})
        result["learning_curve"] = _learning_curve(incidents, fixes_catalog, engine_cfg, p_table, sizes)
    return result
