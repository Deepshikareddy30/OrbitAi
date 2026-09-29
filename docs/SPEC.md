# Incident Trust Engine — Build Spec (Hindsight hackathon)

Give this whole file to Claude Code. Build in the milestone order in section 9.

## 1. What we are building

An incident-response agent for production engineering / DevOps. When an alert arrives it:

1. recalls similar past incidents from **Hindsight** memory,
2. recommends a fix,
3. gives that fix a **trust score computed by math** (not by an LLM),
4. shows the evidence for and against (passed cases vs failed cases),
5. applies an **adaptive approval gate** based on fix risk and trust,
6. records the verified outcome back into Hindsight and **re-learns the weights**, so the next score is better.

The engine is domain-agnostic. The demo world is one simulated instance of it (a generic multi-tenant SaaS platform).

**Non-goals:** no real Slack/PagerDuty/Datadog integrations (we ship synthetic exports), no real infrastructure, no LLM deciding the verdict. An LLM may only write an optional one-line explanation from the computed evidence table; it must never change a number.

**Hackathon rule:** Hindsight must be clearly used. Read the docs at https://hindsight.vectorize.io/ and https://github.com/vectorize-io/hindsight before writing the memory layer. Do not assume SDK method names or tag syntax. Wrap Hindsight behind a small `MemoryStore` interface (`retain`, `recall`, `reflect`) so the rest of the code does not depend on its details. An in-memory fake of that interface is allowed for unit tests only.

## 2. Architecture

| Part | Responsibility |
|---|---|
| Generator (offline) | Simulates the world, writes the dataset, keeps the ground truth hidden |
| Memory layer | Retains every case into Hindsight, recalls candidate similar cases, calls reflect |
| Weighing engine | Learns feature weights, computes similarity, trust score, and the two-sided verdict |
| Adaptive gate | Chooses who must approve, based on fix risk, environment and trust |
| Feedback loop | Runs the outcome check, retains the result, refits weights |
| UI | Incident view (clean workflow, no baseline shown), ranked fixes, Trust Ledger, passed-vs-failed columns, gate, demo upload, AI Health analytics (baseline vs OrbitAI), Audit Log |
| Eval | Held-out metrics, baselines, weight-recovery check, learning curve |

**Division of labour between Hindsight and the engine:** Hindsight is the memory. It stores each case as narrative text plus tags and recalls candidates. The engine keeps the structured feature vectors and the learned weights (derived state, in SQLite or JSON) and does all the math. Join Hindsight results to structured records by `incident_id`.

### 2.1 Tech stack and deployment (confirmed 2026-09-28)

| Layer | Choice | Notes |
|---|---|---|
| Memory | **Hindsight Cloud** (Vectorize-hosted, API key) | Behind the `MemoryStore` interface. Key in `.env`, never committed. |
| Backend | **Python 3.11 + FastAPI** | Generator, engine (numpy / scikit-learn logistic regression), memory layer, gate, feedback loop, eval, API. Run locally with `python -m uvicorn api.app:app --reload` (`uvicorn` alone isn't on PATH in this environment). |
| Derived state | JSON files (versioned weights) / SQLite | Weights, structured case records, audit log. |
| LLM | **Groq** `openai/gpt-oss-120b` | Only the optional one-line explanation (§5.5) and the no-memory baseline (§10.1). Temperature 0, cached for eval. Fallback to template on error. |
| Frontend | **React + Vite + Tailwind** | Incident view, Trust Ledger, gate, demo upload, AI Health, Audit Log. |
| Deploy | Backend on **Render**, frontend on **Vercel** | Both from GitHub. Render free tier sleeps when idle: warm up before the demo. |
| Tests | pytest | Includes the hidden-leak test (§3.3). |

Secrets (`HINDSIGHT_API_KEY`, `GROQ_API_KEY`, etc.) come from environment variables; a `.env.example` documents them.

## 3. Data design

### 3.1 The simulated world

- Generic multi-tenant SaaS platform, 10 services: `api-gateway`, `auth-service`, `tenant-service`, `billing-service`, `workflow-engine`, `notification-service`, `search-service`, `primary-db`, `cache-cluster`, `message-queue`.
- 3 environments: `prod`, `staging`, `canary`.
- About 300 incidents over about 6 months, time-ordered.
- Fault types (hidden root causes), 11, in RCAEval style: `cpu_saturation`, `memory_leak`, `disk_full`, `network_latency`, `packet_loss`, `connection_exhaustion`, `bad_deploy`, `config_error`, `db_saturation`, `dependency_outage`, `cache_stampede`.

### 3.2 Fixes (`fixes.json`)

| Fix | Risk tier | Reversible |
|---|---|---|
| `restart_service` | low | yes |
| `scale_out` | low | yes |
| `toggle_feature_flag` | low | yes |
| `clear_cache` | low | yes |
| `rollback_deploy` | medium | mostly |
| `raise_resource_limits` | medium | yes |
| `drain_node` | medium | mostly |
| `db_failover` | high | no |

### 3.3 Files

| File | Visible to agent? | Contents |
|---|---|---|
| `data/incidents.json` | yes | The case records (3.4), about 300, with a time-based `split` |
| `data/fixes.json` | yes | Fix catalog with risk tiers |
| `data/demo_incidents.json` | yes (uploaded in the demo) | 5 new incidents without outcomes (section 8) |
| `hidden/root_causes.json` | **no** | True root cause per incident |
| `hidden/simulator_matrix.json` | **no** | Success probability for each (root cause × fix) pair |
| `hidden/true_cause_weights.json` | **no** | Which factors truly drove each outcome, per incident |
| `hidden/demo_expected.json` | **no** | Expected verdict for each demo incident |

Only the generator and the evaluator may read `hidden/`. Add a test that fails if any module under `engine/`, `memory/`, `api/` or `ui/` imports or opens a path under `hidden/`.

### 3.4 Incident record (visible fields)

```json
{
  "id": "INC-0042",
  "timestamp": "2026-03-14T09:12:00Z",
  "service": "billing-service",
  "environment": "prod",
  "error_signature": "timeout_upstream_db",
  "symptoms": {"p99_ms": 4200, "error_rate": 0.07, "cpu": 0.91, "mem": 0.62},
  "changes_before": [{"type": "deploy", "detail": "v2.14.1", "minutes_before": 25}],
  "slack_thread": ["short synthetic war-room line", "..."],
  "attempts": [
    {"fix": "restart_service", "outcome": "failed", "time_to_recover_min": null,
     "recurred_within_24h": false, "verified": true,
     "human_override": false, "override_reason": null},
    {"fix": "rollback_deploy", "outcome": "resolved", "time_to_recover_min": 11,
     "recurred_within_24h": false, "verified": true,
     "human_override": true, "override_reason": "deploy was recent"}
  ],
  "contributing_factors": ["recent_deploy", "connection_pool_low"],
  "postmortem_note": "1-2 sentences, this text is retained into Hindsight",
  "split": "train"
}
```

Notes:

- `outcome` is one of `resolved`, `failed`, `recurred`.
- `verified` means a metric check passed (metrics back to normal within the window). Never label success just because someone clicked "resolved".
- `contributing_factors` is what a real postmortem would list. Draw from a fixed vocabulary: `recent_deploy`, `config_change`, `infra_change`, `traffic_spike`, `dependency_degraded`, `resource_limit_low`, `connection_pool_low`, `cache_cold`, `disk_usage_high`, `feature_flag_change`, `version_upgrade`, `schema_migration`. **Make it noisy on purpose:** with a configurable probability drop a true factor, and with another add a red-herring factor.
- The **learned weights are not stored in the dataset.** They are computed by running the backend (section 5).
- `split`: time-based. Oldest about 80% `train`, newest about 20% `held_out`.

### 3.5 How the simulator generates outcomes (hidden truth)

1. Sample a root cause with a prior that depends on service and on whether a change happened before.
2. Generate visible symptoms and `error_signature` from the root cause, **with deliberate overlap between root causes** (look-alikes), so surface symptoms alone do not identify the cause.
3. A simulated on-call picks fixes with a mediocre policy (mix of good and poor choices), so failed attempts exist.
4. Attempt outcome is drawn from `simulator_matrix[root_cause][fix]`, adjusted by hidden per-incident cause weights (for example, a deploy just before makes `restart_service` much less likely to work).
5. Add noise: a small chance of self-healing (looks resolved but was not caused by the fix), a small chance `verified` is false, a small chance of recurrence.
6. Use a fixed random seed. The generator must be reproducible.

**Required look-alike structure:** include many training incidents where symptoms look like a memory leak and `restart_service` resolved them, and a set where symptoms look the same but a deploy happened shortly before and `restart_service` failed (true cause `bad_deploy`). This is what makes the conflict case in the demo possible.

## 4. Memory layer (Hindsight)

**Retain** each attempt (only for `split == train` at startup; new verified outcomes later) as narrative text plus tags. Suggested text:

`[INC-0042] billing-service/prod: timeout_upstream_db. Changes before: deploy v2.14.1 (25 min). Tried restart_service: failed. Postmortem: ... Slack summary: ...`

Tags (check the Hindsight docs for the exact mechanism): `incident_id`, `service`, `env`, `fix`, `outcome`, `verified`, and one tag per contributing factor.

**Recall** with a query built from the present incident (service, error signature, changes before, symptom summary). Take the top N (default 30) candidates, join to structured records by `incident_id`, and hand them to the engine.

**Reflect** after each weight refit. Call Hindsight's reflect to produce observations, and show them in the Trust Ledger as readable notes. **Reflect text is never used in the math.**

**Memory poisoning guard:** only outcomes with `verified == true` from an authorized writer role update weights and scores. Everything else is stored but flagged `unverified` and excluded from the math. The UI must show it as excluded.

## 5. The weighing approach (the core)

### 5.1 Features

For each incident build a feature set: `service`, `environment`, `error_signature`, `symptom_profile` (each of p99, error rate, cpu, mem discretized into 3 bands), `change_types_before` (set), `factor_tags` (set).

Per-feature match `m_f(present, past)`: exact match for categorical features, Jaccard overlap for set features, band match for symptoms. All values are in 0..1.

### 5.2 Reflection: learn the weights by running the backend

For each fix `k`, fit an **L2-regularized logistic regression** on training attempts of that fix: `P(success | x) = sigmoid(b_k + sum_f w_kf * x_f)` where `x` is the incident's one-hot / multi-hot feature vector and success means `resolved` and verified (`failed` and `recurred` count as failure).

- The **signed coefficient `w_kf`** is the cause's contribution to pass (positive) or fail (negative) for that fix. Store it and show it in the Trust Ledger ("`recent_deploy` pushes `restart_service` toward failure, -1.6").
- The **importance `u_kf`** is `|w_kf|` normalized to sum to 1, with a small floor so no feature is ever weight zero.
- **Shrinkage:** blend with global importance (fit across all fixes) using `lambda_k = n_k / (n_k + n0)` (default `n0 = 20`): `u_kf = lambda_k * local + (1 - lambda_k) * global`. Fixes with few cases lean on global weights.
- Save weights as versioned files (`weights_v1.json`, `v2`, ...) so the UI can show the Trust Ledger changing over time.
- Refit when a new verified outcome arrives (cheap at this data size) or on demand from an API endpoint.

### 5.3 Similarity, computed once per (present, past) pair

```
sim(p, c) = recency(c) * ( sum_f u_kf * m_f(p, c) ) / ( sum_f u_kf )
recency(c) = exp(-age_days(c) / tau)      # default tau = 90
```

Cap near-duplicates: at most 3 cases per identical (service, error_signature, factor set) cluster (default, configurable).

### 5.4 Two-sided evidence (the "courtroom", no LLM debate)

For a candidate fix `k` and the present incident:

- **Passed side:** past attempts of `k` that were `resolved` and verified with `sim >= tau_sim`.
- **Failed side:** past attempts of `k` that `failed` or `recurred`, verified, with `sim >= tau_sim`.
- For each side compute the mean similarity of its top-k cases (default 5) and the case count.
- Label a side **High** if its mean `>= hi` and its count `>= n_min`, otherwise **Low**.

| Passed side | Failed side | Verdict |
|---|---|---|
| High | Low | Agree: trust the fix |
| Low | High | Agree: do not trust the fix |
| High | High | Conflict: send to a human, show both columns |
| Low | Low | No evidence: novel incident, human decides |

Trust score for the gate and the ranking:

```
T = (1 + sum_sim_passed) / (2 + sum_sim_passed + risk_mult * sum_sim_failed)
risk_mult: low = 1.0, medium = 1.5, high = 2.0
```

The `1` and `2` pull the score toward 50% when there is little evidence. Always display the case counts next to every score.

**Recommendation:** candidate fixes are those seen in recalled cases. Rank by `T`, tie-break by lower risk tier. Show the full ranking, not just the winner.

Put every threshold (`tau_sim`, `hi`, `n_min`, `k`, `tau`, `n0`, `risk_mult`) in `config.yaml`. Tune `hi`, `n_min`, `tau_sim` on a validation slice of the training data. Never tune on `held_out`.

### 5.5 Optional words layer

An LLM (any; Groq `openai/gpt-oss-120b` is fine) may write a one-line explanation from the computed evidence table. Handle function-calling and timeout errors by falling back to a template string. The explanation must not introduce facts that are not in the table, and it never affects scores, verdicts, or gating.

## 6. Adaptive approval gate

Production incident approval is not enterprise change-board approval: it must be fast, tiered by blast radius and reversibility, and never block on paperwork. Defaults (all in `gate_config.yaml`, tune on validation):

| Fix risk | Rule |
|---|---|
| Low | Auto-run if verdict is "Agree: trust" and `T >= 0.70`, notify on-call. Otherwise one-click on-call approval |
| Medium | One-click on-call approval if "Agree: trust" and `T >= 0.60`. Otherwise escalate to incident commander |
| High | Always human. Two-person approval unless "Agree: trust" and `T >= 0.80` |

Modifiers: `staging` relaxes one level, `prod` uses the table as written. Any "Conflict" or "No evidence" verdict forces at least one-click human approval and displays both evidence columns. Unanswered approvals escalate after a configurable timeout (simulate the timer). Include a break-glass path that always requires a post-incident review entry.

## 7. Feedback loop

1. Approved fix is "executed" against the simulated environment.
2. An outcome check watches simulated metrics for a window and returns `resolved` / `failed` / `recurred` and `time_to_recover_min`. In the demo, the outcome is drawn from the hidden simulator matrix.
3. If the check passed and the writer is authorized, mark `verified = true`, retain to Hindsight, refit weights, save a new weight version, call reflect.
4. The UI shows before/after: the trust score for the next similar incident changed, and why.

**Poisoning test (must exist and be demoable):** submit a fake case claiming a risky fix "always works" from an unauthorized writer or with `verified = false`. It is stored and flagged, excluded from math, and the UI shows it as blocked.

## 8. Demo upload file (`demo_incidents.json`)

Five new incidents (no outcomes), generated with the same generator and fixed seeds, none of them in the training set. Expected results live in `hidden/demo_expected.json`.

| # | Scenario | Expected verdict |
|---|---|---|
| A | Close match to many past passes of one fix, no similar failures | Agree: trust, low-risk fix may auto-run |
| B | Close match to past failures of the obvious fix | Agree: do not trust, a different fix ranks first |
| C | **Look-alike trap:** symptoms match past memory-leak restarts that passed, but a deploy just before matches past restarts that failed | Conflict: human review, both columns shown |
| D | **Novel:** service and fault combination never present in training (generator withholds it) | No evidence: human decides |
| E | Medium-risk fix with borderline trust | Gate escalates to on-call approval |

Demo script: upload the file, walk A to E, execute A and C's chosen fix, watch weights update and the next similar incident's score move. Then open AI Health and its incident-level evaluation view to show the no-memory baseline against OrbitAI. The incident screen itself stays free of baseline comparison.

## 9. Milestones (build in this order)

1. **Generator + validation:** produce the dataset and hidden files, reproducibly. Test the hidden-leak rule and that look-alike structure exists.
2. **Memory layer:** read the Hindsight docs, implement `MemoryStore`, retain all training cases with tags, verify recall returns sensible candidates.
3. **Reflection:** feature building, per-fix logistic fit, shrinkage, versioned weights, Trust Ledger data.
4. **Scoring:** similarity, two-sided evidence, verdict table, trust score, ranked recommendations.
5. **Gate:** rules from `gate_config.yaml`, with tests for each tier and modifier.
6. **Feedback loop:** simulated outcome check, retain, refit, reflect, poisoning guard.
7. **UI + demo upload:** incident view, ranked fixes, passed-vs-failed columns, gate decision, weight history, blocked-memory panel.
8. **Replay evaluation, AI Health views and audit events** (section 10).

## 10. Evaluation flow (simulated replay)

One OrbitAI product, not two. The evaluation is a module (`python -m eval.run`) that writes one results file. The UI and the presentation both read that same file.

### 10.1 Replay procedure

Take the `held_out` incidents in time order. For each incident:

1. **Baseline AI:** the same base LLM used everywhere else in the project, with **no memory**. Input: service, environment, symptoms, `changes_before`, `slack_thread`, plus the fix catalog. Output: a ranked list of fixes chosen from the catalog. Use temperature 0 and cache the answers in `eval/baseline_cache.json` so runs are repeatable and fast.
2. **OrbitAI:** Hindsight recall plus the engine ranking (sections 4 and 5), given exactly the same incident input. No hidden fields.
3. **Score both** against the hidden ground truth (10.2).
4. **Only OrbitAI learns:** simulate executing OrbitAI's top recommended fix, obtain the verified outcome, retain it to Hindsight, refit weights (new version), call reflect. The baseline never changes.

Fairness rules: same base LLM, same fix catalog, same incident inputs for both. The only difference is memory plus the engine.

Optional third line if time allows: "LLM + raw Hindsight recall" (recall results pasted into the prompt, no engine). It isolates what the engine adds beyond memory alone. Skip it if time is short.

### 10.2 Scoring against hidden truth

Per incident and per system:

- `p_success`: probability, from the hidden simulator matrix (adjusted by the hidden cause weights), that the recommended fix resolves this incident. This is the primary metric because it has much less noise than a single sampled outcome.
- `is_best`: 1 if the recommended fix has the highest `p_success` among all fixes for that incident (ties count as best).
- `regret`: best `p_success` minus the recommended fix's `p_success`.
- For OrbitAI only: predicted trust `T`, the verdict, the gate decision, and the sampled verified outcome (used for calibration).

Escalations: when OrbitAI routes to a human (conflict or no evidence), still score its top-ranked fix, and additionally report the escalation rate and the accuracy on the non-escalated subset.

### 10.3 The one results file (`eval/results.json`)

```json
{
  "meta": {"seed": 0, "base_llm": "...", "config_hash": "...", "weight_versions": ["v1", "..."]},
  "incidents": [
    {
      "id": "INC-0251", "timestamp": "...",
      "baseline":  {"fix": "restart_service", "p_success": 0.31, "is_best": false, "regret": 0.52},
      "trustlens": {"fix": "rollback_deploy", "ranked": ["..."], "T": 0.74,
                    "verdict": "agree_trust", "gate": "one_click",
                    "p_success": 0.83, "is_best": true, "regret": 0.0,
                    "sampled_outcome": "resolved", "weights_version": "v14",
                    "n_passed": 6, "n_failed": 1}
    }
  ],
  "aggregates": {
    "rolling_p_success": {"window": 10, "baseline": [], "trustlens": []},
    "cumulative_p_success": {"baseline": [], "trustlens": []},
    "best_fix_rate": {}, "mean_regret": {}, "escalation": {},
    "calibration": [], "brier": 0.0, "auc": 0.0,
    "learning_curve": [], "weight_recovery": {}, "lookalike_subset": {}
  }
}
```

Aggregates to compute: rolling and cumulative `p_success` for each system, best-fix rate, mean regret, calibration table with Brier score and AUC of `T`, learning curve at 50 / 100 / 200 / 300 training incidents, weight recovery (correlation between learned importances and `hidden/true_cause_weights.json`), and the look-alike subset (how often each system picks the wrong fix, and how often OrbitAI flags conflict).

`eval/export_charts.py` reads `results.json` and writes PNG charts for the slides. Nothing is computed inside the slides.

### 10.4 Where it appears in the UI

- **Incident screen:** keep the existing OrbitAI workflow clean: Trust Ledger, evidence (passed vs failed columns), risk, gate, recommendation. Do **not** show the baseline comparison here.
- **AI Health:** overall analytics: baseline vs OrbitAI performance, learning curve, success rate, calibration, and memory impact (retained case count, weight versions over time).
- **Incident-level evaluation:** inside AI Health (or a linked view), pick any past incident and see the baseline and OrbitAI recommendations side by side with their scores. Make this reachable in one click from the demo upload results, so the with/without comparison can be shown in seconds.
- **Audit Log:** record these events: `recommendation_verified`, `memory_retained`, `weights_refit` (with version), `reflect_run`, `gate_decision`, `human_override`, `memory_write_blocked` (poisoning guard), `evaluation_run` (with summary numbers).

### 10.5 Presentation

The PPT shows only the final static charts exported from `results.json`.

### 10.6 Labeling and limits

Label this everywhere (UI and slides) as a **simulated replay evaluation**. In real production only the executed fix's outcome is observed, so an alternative fix's result can never be known. This comparison is possible only because the simulator can score any fix. In production, track trust calibration (predicted vs actual), override rate, and recurrence instead.

### 10.7 Rules

- Train on `train`, evaluate on `held_out` only. Never tune thresholds on `held_out`.
- Report results honestly, including any place where OrbitAI does not beat the baseline.
- Reset flow: `scripts/reset_demo.py` rebuilds the demo memory from the training snapshot (or creates a fresh Hindsight bank per run). Check the Hindsight docs for what it supports. To change the dataset, edit the generator seed or config, regenerate, then rerun `python -m eval.run`.

## 11. Constraints and honesty notes

- The world and all outcomes are simulated. Say so in the README and the pitch. The claim is that the mechanism recovers real structure from noisy outcomes and improves decisions on unseen incidents, not that it has been proven on real production data.
- Trust scores on thin history are unreliable: always show case counts and treat low-count sides as Low.
- Everything reproducible: fixed seeds, versioned weights, config-driven thresholds.
- Clean, documented code and a README that explains exactly where Hindsight is used (retain, recall, reflect) and what the engine does on top of it.
