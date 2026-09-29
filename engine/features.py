"""Feature building for the weighing engine (SPEC S5.1).

Two views of the same incident are produced:
  - `feature_dims`  : a flat one-hot/multi-hot dict {dim_name: 1.0}, the input to the
                      per-fix logistic regression (SPEC S5.2).
  - `feature_groups`: a structured dict {group_name: value_or_set}, used to compute the
                      pairwise match m_f(present, past) for similarity (SPEC S5.1/S5.3).

This module must never read the ground-truth folder that only the generator and
evaluator may touch - see tests/test_hidden_leak.py.
"""

from dataclasses import dataclass

GROUPS = ["service", "environment", "error_signature", "band:p99_ms", "band:error_rate",
         "band:cpu", "band:mem", "change_types", "factors"]
SYMPTOM_FIELDS = ["p99_ms", "error_rate", "cpu", "mem"]
BANDS = ["low", "med", "high"]


@dataclass
class Bands:
    """Tertile cut points per symptom field, fit once on the training set (SPEC S5.1
    'discretized into 3 bands'; the boundaries themselves aren't specified, so we fit
    them from data rather than hand-pick thresholds - see docs/DECISIONS.md ENG1).
    """
    cutpoints: dict[str, tuple[float, float]]

    def band(self, field: str, value: float) -> str:
        lo, hi = self.cutpoints[field]
        return "low" if value <= lo else ("high" if value > hi else "med")

    def to_dict(self):
        return {k: list(v) for k, v in self.cutpoints.items()}

    @classmethod
    def from_dict(cls, d):
        return cls({k: tuple(v) for k, v in d.items()})


def fit_bands(incidents: list[dict]) -> Bands:
    cutpoints = {}
    for field in SYMPTOM_FIELDS:
        vals = sorted(i["symptoms"][field] for i in incidents)
        n = len(vals)
        lo = vals[max(0, n // 3 - 1)]
        hi = vals[max(0, (2 * n) // 3 - 1)]
        cutpoints[field] = (lo, hi)
    return Bands(cutpoints)


def change_types(incident: dict) -> set[str]:
    return {c["type"] for c in incident["changes_before"]}


def factor_set(incident: dict) -> set[str]:
    return set(incident["contributing_factors"])


def feature_groups(incident: dict, bands: Bands) -> dict:
    s = incident["symptoms"]
    return {
        "service": incident["service"],
        "environment": incident["environment"],
        "error_signature": incident["error_signature"],
        "band:p99_ms": bands.band("p99_ms", s["p99_ms"]),
        "band:error_rate": bands.band("error_rate", s["error_rate"]),
        "band:cpu": bands.band("cpu", s["cpu"]),
        "band:mem": bands.band("mem", s["mem"]),
        "change_types": change_types(incident),
        "factors": factor_set(incident),
    }


def feature_dims(incident: dict, bands: Bands) -> dict[str, float]:
    """One-hot for categorical/band groups, multi-hot for set groups."""
    g = feature_groups(incident, bands)
    dims = {}
    for group in ["service", "environment", "error_signature", "band:p99_ms",
                 "band:error_rate", "band:cpu", "band:mem"]:
        dims[f"{group}={g[group]}"] = 1.0
    for c in g["change_types"]:
        dims[f"change_types={c}"] = 1.0
    for f in g["factors"]:
        dims[f"factors={f}"] = 1.0
    return dims


def dim_group(dim_name: str) -> str:
    """Recover which GROUPS entry a one-hot/multi-hot dimension name belongs to."""
    return dim_name.split("=", 1)[0]


def match(group: str, present: dict, past: dict) -> float:
    """m_f(present, past), SPEC S5.1: exact match for categorical, Jaccard for sets,
    band match for symptoms. All in 0..1.
    """
    p, c = present[group], past[group]
    if group in ("change_types", "factors"):
        if not p and not c:
            return 1.0
        union = p | c
        return len(p & c) / len(union) if union else 1.0
    return 1.0 if p == c else 0.0
