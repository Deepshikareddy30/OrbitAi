"""Tune tau_sim, hi, n_min, tau_days on a validation slice of TRAIN (SPEC S5.4: never
tune on held_out). Allowed to read hidden/ for evaluation, like the evaluator - this
script is not under engine/memory/api/ui and never runs at request time.

Validation slice: the newest 20% of the `train` split, scored against the rest of train
(the older 80%) as the candidate pool, so it mimics "a fresh incident vs. history" the
same way the real held_out replay will (SPEC S10.1) without touching held_out itself.

Usage: python -m scripts.tune_thresholds
"""

import itertools
import json
from pathlib import Path

import yaml

from engine.scoring import rank_fixes
from engine.weights import fit_weights
from generator import REPO_ROOT

TAU_SIM_GRID = [0.15, 0.20, 0.25, 0.30, 0.35]
HI_GRID = [0.25, 0.30, 0.35, 0.45]
N_MIN_GRID = [2, 3]
TAU_DAYS_GRID = [90, 150, 220, 365]


def load_p_success():
    weights = json.loads((REPO_ROOT / "hidden" / "true_cause_weights.json").read_text())["incidents"]
    return {iid: {fix: v["p_success"] for fix, v in b.items()} for iid, b in weights.items()}


def main():
    incidents = json.loads((REPO_ROOT / "data" / "incidents.json").read_text())
    fixes_catalog = json.loads((REPO_ROOT / "data" / "fixes.json").read_text())
    fix_names = [f["fix"] for f in fixes_catalog]
    base_cfg = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["engine"]
    p_success = load_p_success()

    train = sorted([i for i in incidents if i["split"] == "train"], key=lambda i: i["timestamp"])
    n_val = max(1, int(len(train) * 0.2))
    history, val = train[:-n_val], train[-n_val:]
    # Weights fit on the older 80% only, so validation incidents are genuinely "held out"
    # from the fit itself, mirroring how held_out will later be scored with weights fit
    # on all of train.
    incidents_for_fit = [dict(i, split=("train" if i in history else "held_out")) for i in incidents]

    best = None
    results = []
    for tau_sim, hi, n_min, tau_days in itertools.product(TAU_SIM_GRID, HI_GRID, N_MIN_GRID, TAU_DAYS_GRID):
        cfg = {**base_cfg, "tau_sim": tau_sim, "hi": hi, "n_min": n_min, "tau_days": tau_days}
        wv = fit_weights(incidents_for_fit, fix_names, cfg, "vtune")

        total_p, best_p, n_scored, n_escalated = 0.0, 0.0, 0, 0
        for inc in val:
            ranked = rank_fixes(inc, history, fixes_catalog, wv, cfg)
            if not ranked:
                continue
            top = ranked[0]
            n_scored += 1
            total_p += p_success[inc["id"]][top.fix]
            best_p += max(p_success[inc["id"]].values())
            if top.verdict in ("conflict", "no_evidence"):
                n_escalated += 1

        if n_scored == 0:
            continue
        mean_p = total_p / n_scored
        regret = (best_p - total_p) / n_scored
        escalation_rate = n_escalated / n_scored
        coverage = n_scored / len(val)
        # Objective: high mean p_success, but don't reward escalating on (almost) everything
        # or answering only a handful of incidents.
        objective = mean_p - 0.15 * max(0.0, escalation_rate - 0.5) - 0.3 * max(0.0, 0.9 - coverage)
        row = dict(tau_sim=tau_sim, hi=hi, n_min=n_min, tau_days=tau_days, mean_p_success=round(mean_p, 4),
                  mean_regret=round(regret, 4), escalation_rate=round(escalation_rate, 3),
                  coverage=round(coverage, 3), objective=round(objective, 4))
        results.append(row)
        if best is None or objective > best["objective"]:
            best = row

    results.sort(key=lambda r: -r["objective"])
    print(json.dumps(results[:10], indent=2))
    print("\nBEST:", json.dumps(best, indent=2))


if __name__ == "__main__":
    main()
