"""Similarity, two-sided evidence, verdict table, trust score, ranking (SPEC S5.3-S5.4).

Pure functions over structured incident dicts - deliberately decoupled from Hindsight.
`candidates` is just "past incidents to consider"; how they were sourced (a live Hindsight
recall joined back to structured records, or - as tests and eval do - the full training
set) is someone else's job. See engine/recall_bridge.py for the live-Hindsight wiring.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from . import features as F

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def age_days(present_ts: str, past_ts: str) -> float:
    return max(0.0, (_parse_ts(present_ts) - _parse_ts(past_ts)).total_seconds() / 86400.0)


def recency(age: float, tau: float) -> float:
    return math.exp(-age / tau)


def weighted_match(present_groups: dict, past_groups: dict, group_importance: dict[str, float]) -> float:
    """sum_f u_kf * m_f(present, past) / sum_f u_kf (SPEC S5.3)."""
    num = sum(group_importance.get(g, 0.0) * F.match(g, present_groups, past_groups) for g in F.GROUPS)
    denom = sum(group_importance.get(g, 0.0) for g in F.GROUPS)
    return num / denom if denom > 0 else 0.0


def similarity(present: dict, past: dict, present_groups: dict, past_groups: dict,
              group_importance: dict[str, float], tau_days: float) -> float:
    """sim(p, c) = recency(c) * weighted_match(p, c) (SPEC S5.3)."""
    a = age_days(present["timestamp"], past["timestamp"])
    return recency(a, tau_days) * weighted_match(present_groups, past_groups, group_importance)


def cluster_key(incident: dict) -> tuple:
    return (incident["service"], incident["error_signature"], frozenset(incident["contributing_factors"]))


def cap_near_duplicates(cases: list[dict], cap: int) -> list[dict]:
    """At most `cap` cases per identical (service, error_signature, factor set) cluster,
    keeping the highest-similarity ones (SPEC S5.3)."""
    by_cluster: dict[tuple, list[dict]] = {}
    for c in cases:
        by_cluster.setdefault(c["cluster_key"], []).append(c)
    kept = []
    for group in by_cluster.values():
        group.sort(key=lambda c: -c["sim"])
        kept.extend(group[:cap])
    kept.sort(key=lambda c: -c["sim"])
    return kept


@dataclass
class SideEvidence:
    label: str          # "high" or "low"
    mean_top_sim: float  # mean similarity of the top-k cases
    count: int           # total cases on this side (post near-dup cap)
    sum_sim: float        # sum of similarity over all cases on this side
    cases: list[dict] = field(default_factory=list)  # top-k, for citation/UI


@dataclass
class FixEvidence:
    fix: str
    risk_tier: str
    passed: SideEvidence
    failed: SideEvidence
    verdict: str   # agree_trust | agree_dont_trust | conflict | no_evidence
    trust: float
    weights_version: str


def _side(cases: list[dict], cfg: dict) -> SideEvidence:
    capped = cap_near_duplicates(cases, cfg["near_duplicate_cap"])
    count = len(capped)
    sum_sim = sum(c["sim"] for c in capped)
    top = sorted(capped, key=lambda c: -c["sim"])[: cfg["top_k"]]
    mean_top = sum(c["sim"] for c in top) / len(top) if top else 0.0
    label = "high" if (mean_top >= cfg["hi"] and count >= cfg["n_min"]) else "low"
    return SideEvidence(label=label, mean_top_sim=round(mean_top, 4), count=count,
                        sum_sim=round(sum_sim, 4), cases=top)


VERDICTS = {
    ("high", "low"): "agree_trust",
    ("low", "high"): "agree_dont_trust",
    ("high", "high"): "conflict",
    ("low", "low"): "no_evidence",
}


def score_fix(fix: str, risk_tier: str, present: dict, present_groups: dict,
             candidates: list[dict], weights_version, cfg: dict) -> FixEvidence:
    fw = weights_version.per_fix[fix]
    passed_cases, failed_cases = [], []
    for past in candidates:
        past_groups = F.feature_groups(past, _bands(weights_version))
        sim = similarity(present, past, present_groups, past_groups, fw.group_importance, cfg["tau_days"])
        if sim < cfg["tau_sim"]:
            continue
        for attempt in past["attempts"]:
            if attempt["fix"] != fix or not attempt["verified"]:
                continue
            case = {
                "incident_id": past["id"], "sim": round(sim, 4), "timestamp": past["timestamp"],
                "outcome": attempt["outcome"], "time_to_recover_min": attempt["time_to_recover_min"],
                "cluster_key": cluster_key(past),
            }
            (passed_cases if attempt["outcome"] == "resolved" else failed_cases).append(case)

    passed = _side(passed_cases, cfg)
    failed = _side(failed_cases, cfg)
    verdict = VERDICTS[(passed.label, failed.label)]

    risk_mult = cfg["risk_mult"][risk_tier]
    trust = (1 + passed.sum_sim) / (2 + passed.sum_sim + risk_mult * failed.sum_sim)

    return FixEvidence(fix=fix, risk_tier=risk_tier, passed=passed, failed=failed,
                       verdict=verdict, trust=round(trust, 4), weights_version=weights_version.version)


def _bands(weights_version) -> F.Bands:
    return F.Bands.from_dict(weights_version.bands)


def candidate_fixes(candidates: list[dict]) -> list[str]:
    """Fixes actually seen in the recalled candidates (SPEC S5.4: 'candidate fixes are
    those seen in recalled cases')."""
    seen = []
    for c in candidates:
        for a in c["attempts"]:
            if a["verified"] and a["fix"] not in seen:
                seen.append(a["fix"])
    return seen


VERDICT_QUALITY_ORDER = {"agree_trust": 0, "conflict": 1, "no_evidence": 2, "agree_dont_trust": 3}


def rank_fixes(present: dict, candidates: list[dict], fixes_catalog: list[dict],
              weights_version, cfg: dict, verdict_priority: bool = False) -> list[FixEvidence]:
    """Rank by trust desc, tie-break by lower risk tier (SPEC S5.4).

    `verdict_priority=True` sorts by evidence *quality* first (agree_trust > conflict >
    no_evidence > agree_dont_trust), trust descending within each tier - so a fix with 1-2
    thin all-pass cases (no_evidence, since it doesn't clear n_min) can't outrank one with
    real, substantial supporting evidence (agree_trust) just because raw Bayesian-smoothed
    T happens to be a little higher on threadbare evidence. Off by default so every
    already-verified caller (demo A-E, eval replay) keeps its exact prior numbers -
    opt-in per SPEC S5.4's own ranking rule being silent on this, not a change to it.
    """
    risk_by_fix = {f["fix"]: f["risk_tier"] for f in fixes_catalog}
    present_groups = F.feature_groups(present, _bands(weights_version))
    fixes = [f for f in candidate_fixes(candidates) if f in weights_version.per_fix]
    scored = [score_fix(fix, risk_by_fix[fix], present, present_groups, candidates, weights_version, cfg)
             for fix in fixes]
    if verdict_priority:
        scored.sort(key=lambda fe: (VERDICT_QUALITY_ORDER[fe.verdict], -fe.trust, RISK_ORDER[fe.risk_tier]))
    else:
        scored.sort(key=lambda fe: (-fe.trust, RISK_ORDER[fe.risk_tier]))
    return scored
