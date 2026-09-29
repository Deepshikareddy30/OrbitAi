"""Incident simulator (SPEC §3.5). Produces visible incident records plus hidden truth."""

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from . import world as W


def _pick(rng, weights: dict):
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return keys[rng.choice(len(keys), p=p / p.sum())]


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z))


# ---------------------------------------------------------------------------
# Incident context: root cause, changes, symptoms, factors
# ---------------------------------------------------------------------------

def sample_root_cause(rng, service, has_change, withheld):
    weights = {}
    for rc, w in W.SERVICE_FAULTS[service].items():
        if (service, rc) == withheld:
            continue
        if rc in W.CHANGE_DRIVEN:
            w = w * W.CHANGE_BOOST if has_change else 0.0
        weights[rc] = w
    if sum(weights.values()) == 0:
        return None
    return _pick(rng, weights)


def make_changes(rng, service, root_cause, has_change):
    """Visible changes_before list. Change-driven faults always have their causal change."""
    if root_cause == "bad_deploy":
        major = rng.random() < 0.3
        version = f"v{rng.integers(2, 6)}.{0 if major else rng.integers(1, 20)}.{rng.integers(0, 10)}"
        return [{"type": "deploy", "detail": version, "minutes_before": int(rng.integers(5, 46))}], major
    if root_cause == "config_error":
        ctype = "config_change" if rng.random() < 0.6 else "feature_flag"
        detail = f"{service.split('-')[0]}.{rng.choice(['timeouts', 'pool', 'routing', 'limits', 'retries'])}"
        return [{"type": ctype, "detail": detail, "minutes_before": int(rng.integers(5, 61))}], False
    if not has_change:
        return [], False
    weights = dict(W.BENIGN_CHANGE_WEIGHTS)
    if service not in W.DB_SERVICES:
        weights.pop("schema_migration")
    ctype = _pick(rng, weights)
    detail = {
        "deploy": f"v{rng.integers(2, 6)}.{rng.integers(1, 20)}.{rng.integers(0, 10)}",
        "config_change": f"{service.split('-')[0]}.{rng.choice(['log_level', 'batch_size', 'timeouts'])}",
        "infra_change": rng.choice(["node pool upgrade", "LB rule update", "CNI patch"]),
        "feature_flag": f"ff_{rng.choice(['new_ui', 'bulk_export', 'async_jobs'])}",
        "schema_migration": f"migration_{rng.integers(100, 400)}",
    }[ctype]
    return [{"type": ctype, "detail": str(detail), "minutes_before": int(rng.integers(10, 181))}], False


def make_symptoms(rng, signature):
    p99, err, cpu, mem = W.SIGNATURE_PROFILE[signature]
    return {
        "p99_ms": int(round(p99 * rng.lognormal(0, 0.25), -1)),
        "error_rate": round(float(np.clip(err * rng.lognormal(0, 0.3), 0.001, 0.9)), 3),
        "cpu": round(float(np.clip(cpu + rng.normal(0, 0.05), 0.05, 1.0)), 2),
        "mem": round(float(np.clip(mem + rng.normal(0, 0.05), 0.05, 1.0)), 2),
    }


def true_factors_for(rng, root_cause, changes, major_upgrade):
    factors = set()
    for f, p in W.ROOT_FACTORS[root_cause].items():
        if rng.random() < p:
            factors.add(f)
    for c in changes:
        f = W.CHANGE_FACTOR[c["type"]]
        if f == "recent_deploy" and c["minutes_before"] > W.RECENT_DEPLOY_MINUTES:
            continue
        factors.add(f)
    if major_upgrade:
        factors.add("version_upgrade")
    return factors


def noisy_factors(rng, true_factors, cfg):
    """What the postmortem lists: drops some true factors, adds a red herring sometimes.

    Iterates sorted(true_factors), not the set directly: Python's set iteration order
    depends on PYTHONHASHSEED (randomized per-process by default), which would otherwise
    make which rng.random() draw lands on which factor non-reproducible across process
    runs even with a fixed numpy seed - see docs/DECISIONS.md G6.
    """
    visible = {f for f in sorted(true_factors) if rng.random() >= cfg["p_drop_true_factor"]}
    if rng.random() < cfg["p_red_herring_factor"]:
        candidates = [f for f in W.FACTOR_VOCAB if f not in true_factors]
        visible.add(candidates[rng.integers(len(candidates))])
    return sorted(visible)


def fix_breakdown(root_cause, true_factors, changes):
    """HIDDEN: per-fix base logit, active modifier contributions and final p_success."""
    active = set(true_factors)
    if not any(c["type"] in ("deploy", "config_change", "feature_flag") for c in changes):
        active.add("no_recent_change")
    out = {}
    for fix in W.FIX_NAMES:
        base = _logit(W.SIMULATOR_MATRIX[root_cause][fix])
        contrib = {f: W.HIDDEN_MODIFIERS[f][fix] for f in sorted(active)
                   if fix in W.HIDDEN_MODIFIERS.get(f, {})}
        out[fix] = {"base_logit": round(base, 4), "contributions": contrib,
                    "p_success": round(_sigmoid(base + sum(contrib.values())), 4)}
    return out


# ---------------------------------------------------------------------------
# On-call behaviour and outcomes
# ---------------------------------------------------------------------------

def choose_fix(rng, signature, service, changes, tried, breakdown):
    """Mediocre on-call policy. Returns (fix, human_override, override_reason)."""
    runbook = [f for f in W.RUNBOOK[signature] if f not in tried]
    follow_p = 0.85 if (signature in W.STRONG_RUNBOOK and not tried) else 0.55
    recent_change = any(c["minutes_before"] <= W.RECENT_DEPLOY_MINUTES and
                        c["type"] in ("deploy", "config_change", "feature_flag") for c in changes)
    u = rng.random()
    if runbook and u < follow_p:
        return runbook[0], False, None
    if recent_change and "rollback_deploy" not in tried and u < follow_p + 0.15:
        return "rollback_deploy", True, "change was recent"
    untried = [f for f in W.FIX_NAMES if f not in tried]
    if service not in W.DB_SERVICES:
        untried = [f for f in untried if f != "db_failover"] or untried
    if u < follow_p + 0.30:
        best = max(untried, key=lambda f: breakdown[f]["p_success"])
        return best, True, "on-call judged the runbook step would not help"
    return untried[rng.integers(len(untried))], True, "trying a different approach"


def simulate_attempt_outcome(fix, breakdown, cfg, rng, *, override=False, override_reason=None):
    """Draw one attempt's outcome from the hidden breakdown (SPEC S3.5 step 4-5). Shared by
    run_attempts (dataset generation) and generator.executor (on-demand feedback-loop
    execution, SPEC S7) so the noise model - self-heal, unverified click, recurrence -
    only lives in one place. Returns (visible attempt, hidden debug dict).
    """
    worked = rng.random() < breakdown[fix]["p_success"]
    ttr_typ = W.FIX_BY_NAME[fix]["typical_ttr_min"]
    ttr = max(1, int(round(ttr_typ * rng.lognormal(0, 0.35))))
    a = {"fix": fix, "outcome": "failed", "time_to_recover_min": None,
        "recurred_within_24h": False, "verified": True,
        "human_override": override, "override_reason": override_reason}
    h = {"fix": fix, "fix_worked": bool(worked), "self_healed": False, "clicked_resolved": False}
    if worked:
        if rng.random() < cfg["p_recur"]:
            a.update(outcome="recurred", time_to_recover_min=ttr, recurred_within_24h=True)
        else:
            a.update(outcome="resolved", time_to_recover_min=ttr)
    elif rng.random() < cfg["p_self_heal"]:
        a.update(outcome="resolved", time_to_recover_min=ttr + int(rng.integers(5, 30)))
        h["self_healed"] = True
    elif rng.random() < cfg["p_unverified"]:
        a.update(outcome="resolved", time_to_recover_min=ttr, verified=False)
        h["clicked_resolved"] = True
    return a, h


def run_attempts(rng, signature, service, changes, breakdown, cfg):
    """Simulate attempts until resolved or max_attempts. Returns (visible, hidden) lists."""
    attempts, hidden = [], []
    tried = []
    for _ in range(cfg["max_attempts"]):
        fix, override, reason = choose_fix(rng, signature, service, changes, tried, breakdown)
        tried.append(fix)
        a, h = simulate_attempt_outcome(fix, breakdown, cfg, rng, override=override, override_reason=reason)
        attempts.append(a)
        hidden.append(h)
        if a["outcome"] == "resolved":
            break
        if a["outcome"] == "recurred" and rng.random() > 0.6:
            break
    return attempts, hidden


# ---------------------------------------------------------------------------
# Narrative text (never names the hidden root cause, DECISIONS G1)
# ---------------------------------------------------------------------------

def slack_thread(service, env, signature, symptoms, changes, attempts):
    lines = [f"@oncall {service} ({env}) paging: {W.SIGNATURE_TEXT[signature]}, "
             f"p99 {symptoms['p99_ms']}ms, errors {symptoms['error_rate']:.1%}"]
    for c in changes:
        lines.append(f"anyone ship something? I see {c['type'].replace('_', ' ')} {c['detail']} "
                     f"{c['minutes_before']} min ago")
    for a in attempts:
        fix = a["fix"].replace("_", " ")
        if a["outcome"] == "resolved":
            lines.append(f"tried {fix}, looks recovered" + ("" if a["verified"] else ", closing"))
        elif a["outcome"] == "recurred":
            lines.append(f"{fix} helped but it came back")
        else:
            lines.append(f"{fix} didn't help")
    return lines[:6]


def postmortem_note(service, env, signature, symptoms, factors, attempts):
    fac = ", ".join(f.replace("_", " ") for f in factors) or "none identified"
    first = attempts[0]
    last = attempts[-1]
    s1 = (f"{service} in {env} showed {W.SIGNATURE_TEXT[signature]} "
          f"(p99 {symptoms['p99_ms']}ms, error rate {symptoms['error_rate']:.1%}); "
          f"contributing factors: {fac}.")
    if last["outcome"] == "resolved" and last["verified"]:
        tail = f"{last['fix']} restored service in {last['time_to_recover_min']} min"
    elif last["outcome"] == "resolved":
        tail = f"closed after {last['fix']} but metrics were not confirmed healthy"
    elif last["outcome"] == "recurred":
        tail = f"{last['fix']} helped temporarily but the issue recurred"
    else:
        tail = "no attempted fix resolved it; escalated"
    if len(attempts) > 1:
        s2 = f"First tried {first['fix']} ({first['outcome']}); {tail}."
    else:
        s2 = tail[0].upper() + tail[1:] + "."
    return f"{s1} {s2}"


# ---------------------------------------------------------------------------
# Whole-dataset generation
# ---------------------------------------------------------------------------

def make_context(rng, cfg, service=None, env=None, root_cause=None, signature=None,
                 changes=None, factors=None, withheld=None):
    """Sample (or force, for demo incidents) the incident context."""
    service = service or _pick(rng, W.SERVICE_WEIGHTS)
    env = env or _pick(rng, W.ENVIRONMENTS)
    has_change = rng.random() < cfg["p_change_before"]
    major = False
    if root_cause is None:
        root_cause = sample_root_cause(rng, service, has_change, withheld)
        while root_cause is None:  # service has no admissible fault; resample service
            service = _pick(rng, W.SERVICE_WEIGHTS)
            root_cause = sample_root_cause(rng, service, has_change, withheld)
    if changes is None:
        changes, major = make_changes(rng, service, root_cause, has_change)
    if signature is None:
        dist = W.SIGNATURES[root_cause]
        if service in W.LEAK_PRONE_SERVICES:
            dist = W.SIGNATURE_OVERRIDES.get((root_cause, "leak_prone"), dist)
        signature = _pick(rng, dist)
    symptoms = make_symptoms(rng, signature)
    true_f = true_factors_for(rng, root_cause, changes, major)
    visible_f = noisy_factors(rng, true_f, cfg) if factors is None else sorted(factors)
    breakdown = fix_breakdown(root_cause, true_f, changes)
    return {"service": service, "environment": env, "root_cause": root_cause,
            "signature": signature, "symptoms": symptoms, "changes": changes,
            "true_factors": sorted(true_f), "visible_factors": visible_f, "breakdown": breakdown}


def generate(cfg):
    rng = np.random.default_rng(cfg["seed"])
    withheld = (cfg["withheld_combo"]["service"], cfg["withheld_combo"]["root_cause"])
    start = datetime.fromisoformat(cfg["start"].replace("Z", "+00:00")).astimezone(timezone.utc)
    offsets = np.sort(rng.uniform(0, cfg["days"] * 24 * 60, cfg["n_incidents"]))
    n_train = int(round(cfg["n_incidents"] * (1 - cfg["held_out_fraction"])))

    incidents, root_causes, weights = [], {}, {}
    for i, minutes in enumerate(offsets):
        iid = f"INC-{i + 1:04d}"
        ts = (start + timedelta(minutes=float(minutes))).replace(second=0, microsecond=0)
        ctx = make_context(rng, cfg, withheld=withheld)
        attempts, hidden_attempts = run_attempts(
            rng, ctx["signature"], ctx["service"], ctx["changes"], ctx["breakdown"], cfg)
        incidents.append({
            "id": iid,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "service": ctx["service"],
            "environment": ctx["environment"],
            "error_signature": ctx["signature"],
            "symptoms": ctx["symptoms"],
            "changes_before": ctx["changes"],
            "slack_thread": slack_thread(ctx["service"], ctx["environment"], ctx["signature"],
                                         ctx["symptoms"], ctx["changes"], attempts),
            "attempts": attempts,
            "contributing_factors": ctx["visible_factors"],
            "postmortem_note": postmortem_note(ctx["service"], ctx["environment"], ctx["signature"],
                                               ctx["symptoms"], ctx["visible_factors"], attempts),
            "split": "train" if i < n_train else "held_out",
        })
        root_causes[iid] = {"root_cause": ctx["root_cause"], "true_factors": ctx["true_factors"],
                            "attempts": hidden_attempts}
        weights[iid] = ctx["breakdown"]
    return incidents, root_causes, weights, rng
