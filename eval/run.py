"""Replay evaluation (SPEC S10): baseline (no memory) vs OrbitAI (Hindsight recall +
engine), replayed over held_out in time order. Only OrbitAI learns from each verified
outcome as it goes; the baseline never changes. Writes the one results file both the UI
and the presentation read (`eval/results.json`).

Usage: python -m eval.run [--out eval/results.json]
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

from engine.gate import decide as gate_decide
from engine.recall_bridge import recall_candidates
from engine.scoring import rank_fixes
from engine.weights import fit_and_save, list_versions, load_latest
from feedback.loop import apply_outcome
from generator import REPO_ROOT, load_config
from generator.executor import execute_fix
from memory.fake_store import InMemoryStore
from memory.loader import retain_all_train

from .aggregates import compute_aggregates
from .baseline import get_baseline, load_cache, save_cache
from .truth import load_p_success_table, load_root_causes, score_recommendation

log = logging.getLogger("eval.run")

BANK_ID = "trustlens-eval"
SEED = 0


def _config_hash(engine_cfg: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(engine_cfg, sort_keys=True).encode()).hexdigest()[:12]


def run(repo_root: Path = REPO_ROOT, out_path: Path | None = None) -> dict:
    incidents = json.loads((repo_root / "data" / "incidents.json").read_text())
    fixes_catalog = json.loads((repo_root / "data" / "fixes.json").read_text())
    engine_cfg = yaml.safe_load((repo_root / "config.yaml").read_text())["engine"]
    gate_cfg = yaml.safe_load((repo_root / "gate_config.yaml").read_text())
    fix_names = [f["fix"] for f in fixes_catalog]
    risk_by_fix = {f["fix"]: f["risk_tier"] for f in fixes_catalog}

    p_table = load_p_success_table(repo_root)
    root_causes = load_root_causes(repo_root)

    weights_root = repo_root / "eval" / "run_weights"
    if weights_root.exists():
        for p in (weights_root / "weights").glob("weights_v*.json"):
            p.unlink()
    store = InMemoryStore()
    retain_all_train(store, BANK_ID, incidents)
    fit_and_save(incidents, fix_names, engine_cfg, weights_root)  # v1, pre-replay

    cache_path = repo_root / "eval" / "baseline_cache.json"
    baseline_cache = load_cache(cache_path)
    api_key = os.environ.get("GROQ_API_KEY")

    # A pristine snapshot for aggregates that need the ORIGINAL train/held_out partition
    # (learning_curve): `incidents` itself gets mutated during replay - each held_out
    # incident OrbitAI learns from flips to split='train' (SPEC S7), which is correct
    # for the incremental replay but would corrupt a train-size sweep computed afterward.
    original_incidents = json.loads(json.dumps(incidents))

    incidents_by_id = {i["id"]: i for i in incidents}
    held_out = sorted([i for i in incidents if i["split"] == "held_out"], key=lambda i: i["timestamp"])
    rng = np.random.default_rng(SEED)
    gen_cfg = load_config()

    # eval-only recall width: see docs/DECISIONS.md EVAL2. The fake store's naive
    # keyword-overlap recall is measurably weaker than real Hindsight retrieval - verified
    # it can miss a strong candidate (T=0.72 agree_trust) entirely at recall_top_n=30. Cast
    # a much wider net here so this replay measures the Trust Ledger's reasoning quality,
    # not the toy fake's retrieval quality. config.yaml's recall_top_n=30 remains the
    # production default for real Hindsight, unaffected by this override.
    using_real_hindsight = type(store).__module__.endswith("hindsight_store")
    eval_recall_top_n = engine_cfg["recall_top_n"] if using_real_hindsight else min(200, len(incidents))

    rows = []
    weight_versions_seen = ["v1"]
    for inc in held_out:
        wv = load_latest(weights_root)

        # -- baseline: same inputs, no memory --------------------------------
        b_entry = get_baseline(inc, fixes_catalog, baseline_cache, api_key)
        b_fix = b_entry["ranked"][0]
        b_score = score_recommendation(inc["id"], b_fix, p_table)

        # -- OrbitAI: Hindsight recall + engine ranking ----------------------
        candidates = recall_candidates(store, BANK_ID, inc, incidents_by_id, top_n=eval_recall_top_n)
        ranked = rank_fixes(inc, candidates, fixes_catalog, wv, engine_cfg) if wv.per_fix else []
        if ranked:
            top = ranked[0]
            gate = gate_decide(top.fix, top.risk_tier, inc["environment"], top.verdict, top.trust, gate_cfg)
            t_fix, t_verdict, t_trust = top.fix, top.verdict, top.trust
        else:
            t_fix, t_verdict, t_trust = "restart_service", "no_evidence", 0.5
            gate = gate_decide(t_fix, risk_by_fix[t_fix], inc["environment"], t_verdict, t_trust, gate_cfg)
        t_score = score_recommendation(inc["id"], t_fix, p_table)

        # -- only OrbitAI learns: execute its top pick, verify, retain, refit --
        true = root_causes[inc["id"]]
        attempt, _hidden = execute_fix(true["root_cause"], set(true["true_factors"]),
                                       inc["changes_before"], t_fix, gen_cfg, rng)
        fb = apply_outcome(inc, attempt, writer="eval-replay", authorized=True, store=store, bank_id=BANK_ID,
                           incidents=incidents, fixes=fix_names, cfg=engine_cfg, weights_root=weights_root)
        if fb.weights_version:
            weight_versions_seen.append(fb.weights_version)

        n_passed = top.passed.count if ranked else 0
        n_failed = top.failed.count if ranked else 0
        rows.append({
            "id": inc["id"], "timestamp": inc["timestamp"], "_signature": inc["error_signature"],
            "baseline": {**b_score, "used_llm": b_entry["used_llm"]},
            "trustlens": {**t_score, "ranked": [fe.fix for fe in ranked], "T": round(t_trust, 4),
                         "verdict": t_verdict, "gate": gate.action, "sampled_outcome": attempt["outcome"],
                         "sampled_verified": attempt["verified"], "weights_version": wv.version,
                         "n_passed": n_passed, "n_failed": n_failed},
        })

    save_cache(cache_path, baseline_cache)

    meta = {
        "seed": SEED, "base_llm": "openai/gpt-oss-120b (groq)" if api_key else "heuristic-fallback (no GROQ_API_KEY)",
        "config_hash": _config_hash(engine_cfg), "weight_versions": list_versions(weights_root),
        "n_held_out": len(held_out), "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "memory_store": "hindsight" if using_real_hindsight else "fake (in-memory keyword-overlap stand-in)",
        "recall_top_n_used": eval_recall_top_n,
        "note": None if using_real_hindsight else (
            "Recall used the InMemoryStore fake (no HINDSIGHT_API_KEY configured), widened to "
            f"top_n={eval_recall_top_n} to avoid the fake's naive keyword-overlap retrieval "
            "bottlenecking these numbers - see docs/DECISIONS.md EVAL2."),
    }
    aggregates = compute_aggregates(rows, original_incidents, repo_root, engine_cfg, weights_root=weights_root,
                                    fixes_catalog=fixes_catalog, p_table=p_table)
    results = {"meta": meta, "incidents": rows, "aggregates": aggregates}

    out_path = out_path or (repo_root / "eval" / "results.json")
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Wrote %s (%d held-out incidents)", out_path, len(rows))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    results = run(out_path=Path(args.out) if args.out else None)
    agg = results["aggregates"]
    print(json.dumps({"meta": results["meta"], "best_fix_rate": agg["best_fix_rate"],
                      "mean_regret": agg["mean_regret"], "escalation": agg["escalation"]}, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
