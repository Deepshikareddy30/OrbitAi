"""Reflection: learn per-fix feature weights from verified training outcomes (SPEC S5.2).

Design note (docs/DECISIONS.md ENG2): SPEC S5.2 fits one-hot/multi-hot logistic
regression per fix and calls the signed coefficient w_kf a *cause's* contribution,
while S5.3's similarity formula sums u_kf over *feature groups* (service, environment,
...). We reconcile the two by fitting logistic regression at value-level (one coefficient
per "service=billing-service", "factors=recent_deploy", etc. - this is what lets the
Trust Ledger say "recent_deploy pushes restart_service toward failure, -1.6"), then
building each *group's* importance for similarity by summing the (already-normalized)
value-level importances that belong to that group. Because value importances sum to 1
across all dims, group importances automatically sum to 1 across all groups too.

Only verified attempts train the model (poisoning guard, SPEC S4/S5): unverified
"resolved" clicks are excluded from the math entirely, not counted as failures.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from . import features as F

log = logging.getLogger("engine.weights")

WEIGHTS_DIR_NAME = "weights"
VERSION_RE = re.compile(r"^weights_v(\d+)\.json$")


@dataclass
class FixWeights:
    n_train: int
    lambda_k: float
    local_coef: dict[str, float]     # empty if n_train == 0
    importance: dict[str, float]     # value-level u_kf, sums to 1 (with floor)
    group_importance: dict[str, float]  # sum of value-level u_kf within each group
    top_signed: list[dict]           # for Trust Ledger narrative


@dataclass
class WeightsVersion:
    version: str
    fitted_at: str
    n0: int
    l2_C: float
    importance_floor: float
    bands: dict
    all_dims: list[str]
    global_coef: dict[str, float]
    global_importance: dict[str, float]
    per_fix: dict[str, FixWeights] = field(default_factory=dict)

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items() if k != "per_fix"}
        d["per_fix"] = {fix: {**w.__dict__} for fix, w in self.per_fix.items()}
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        per_fix = {fix: FixWeights(**w) for fix, w in d.pop("per_fix", {}).items()}
        return cls(per_fix=per_fix, **d)


def _normalize_with_floor(coef: dict[str, float], all_dims: list[str], floor: float) -> dict[str, float]:
    """|coef| normalized to sum to 1, with a small floor so no dim is ever exactly zero
    (SPEC S5.2: 'a small floor so no feature is ever weight zero').

    Implemented as a smoothing mix-in - u_v = (1-floor)*raw_v + floor*(1/n) - rather than
    an absolute per-dim minimum, because an absolute floor is infeasible once there are
    more than 1/floor dims (with ~50+ one-hot/multi-hot dims and floor=0.02, 50*0.02 is
    already >= 1.0). The mix-in always sums to exactly 1 and still guarantees every dim
    at least floor/n of the mass - see docs/DECISIONS.md ENG3.
    """
    mags = {d: abs(coef.get(d, 0.0)) for d in all_dims}
    total = sum(mags.values())
    n = len(all_dims)
    if total <= 0:
        return {d: 1.0 / n for d in all_dims}
    raw = {d: m / total for d, m in mags.items()}
    return {d: (1 - floor) * v + floor * (1.0 / n) for d, v in raw.items()}


def _group_importance(value_importance: dict[str, float]) -> dict[str, float]:
    out = {g: 0.0 for g in F.GROUPS}
    for dim, u in value_importance.items():
        out[F.dim_group(dim)] += u
    return out


def _verified_attempts(incidents: list[dict], fix: str | None = None):
    """(incident, attempt) pairs from train, verified only. fix=None -> all fixes (global)."""
    for inc in incidents:
        if inc["split"] != "train":
            continue
        for a in inc["attempts"]:
            if not a["verified"]:
                continue
            if fix is not None and a["fix"] != fix:
                continue
            yield inc, a


def _fit_logreg(rows: list[dict], labels: list[int], vec: DictVectorizer, C: float):
    if len(set(labels)) < 2 or len(rows) == 0:
        return None
    X = vec.transform(rows)
    clf = LogisticRegression(C=C, max_iter=1000)  # penalty defaults to l2
    clf.fit(X, labels)
    return dict(zip(vec.get_feature_names_out(), clf.coef_[0]))


def fit_weights(incidents: list[dict], fixes: list[str], cfg: dict, version: str) -> WeightsVersion:
    train = [i for i in incidents if i["split"] == "train"]
    # Only incidents with at least one verified attempt may define the feature space
    # (band cut points, one-hot/multi-hot vocabulary). Otherwise an incident carrying
    # only unverified/unauthorized attempts - fully excluded from every training row -
    # could still perturb every fix's learned weights indirectly, through the shared
    # normalization denominator (docs/DECISIONS.md ENG8). This is what "excluded from
    # the math" (SPEC S4/S5.4) has to mean, not just "excluded from the training labels".
    feature_space = [i for i in train if any(a["verified"] for a in i["attempts"])]
    bands = F.fit_bands(feature_space)

    all_dims_set: set[str] = set()
    dims_by_key: dict[tuple, dict] = {}
    for inc in feature_space:
        d = F.feature_dims(inc, bands)
        all_dims_set.update(d)
        dims_by_key[inc["id"]] = d
    all_dims = sorted(all_dims_set)
    vec = DictVectorizer(sparse=True)
    vec.fit([{d: 1.0 for d in all_dims}])  # fixes the column order/vocabulary

    floor = cfg["importance_floor"]
    n0 = cfg["n0"]
    C = cfg["l2_C"]

    # Global fit: pooled across all fixes.
    g_rows, g_labels = [], []
    for inc, a in _verified_attempts(train):
        g_rows.append(dims_by_key[inc["id"]])
        g_labels.append(1 if a["outcome"] == "resolved" else 0)
    global_coef = _fit_logreg(g_rows, g_labels, vec, C) or {}
    global_importance = _normalize_with_floor(global_coef, all_dims, floor)

    per_fix = {}
    for fix in fixes:
        rows, labels = [], []
        for inc, a in _verified_attempts(train, fix=fix):
            rows.append(dims_by_key[inc["id"]])
            labels.append(1 if a["outcome"] == "resolved" else 0)
        n_k = len(rows)
        local_coef = _fit_logreg(rows, labels, vec, C) or {}
        # When there's no usable local fit (too few rows, or only one outcome class seen),
        # fall back to the (already floored/normalized) global importance rather than a
        # flat uniform distribution, which can itself violate the floor when there are
        # more dims than 1/floor.
        local_importance = _normalize_with_floor(local_coef, all_dims, floor) if local_coef else \
            dict(global_importance)
        lambda_k = n_k / (n_k + n0)
        blended = {d: lambda_k * local_importance[d] + (1 - lambda_k) * global_importance[d]
                  for d in all_dims}
        coef_for_narrative = local_coef if local_coef else global_coef
        top_signed = sorted(
            ({"dim": d, "coef": round(c, 3)} for d, c in coef_for_narrative.items() if abs(c) > 1e-6),
            key=lambda r: -abs(r["coef"]),
        )[:8]
        per_fix[fix] = FixWeights(
            n_train=n_k, lambda_k=round(lambda_k, 4),
            local_coef={d: round(c, 4) for d, c in local_coef.items()},
            importance={d: round(v, 5) for d, v in blended.items()},
            group_importance={g: round(v, 5) for g, v in _group_importance(blended).items()},
            top_signed=top_signed,
        )

    return WeightsVersion(
        version=version, fitted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        n0=n0, l2_C=C, importance_floor=floor, bands=bands.to_dict(), all_dims=all_dims,
        global_coef={d: round(c, 4) for d, c in global_coef.items()},
        global_importance={d: round(v, 5) for d, v in global_importance.items()},
        per_fix=per_fix,
    )


# --------------------------------------------------------------------------
# Versioned persistence (SPEC S5.2: 'Save weights as versioned files')
# --------------------------------------------------------------------------

def _weights_dir(root: Path) -> Path:
    d = root / WEIGHTS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_versions(root: Path) -> list[str]:
    nums = []
    for p in _weights_dir(root).glob("weights_v*.json"):
        m = VERSION_RE.match(p.name)
        if m:
            nums.append(int(m.group(1)))
    return [f"v{n}" for n in sorted(nums)]


def next_version(root: Path) -> str:
    versions = list_versions(root)
    n = max((int(v[1:]) for v in versions), default=0) + 1
    return f"v{n}"


def save(root: Path, wv: WeightsVersion) -> Path:
    path = _weights_dir(root) / f"weights_{wv.version}.json"
    path.write_text(json.dumps(wv.to_dict(), indent=2), encoding="utf-8")
    log.info("Saved weights %s to %s", wv.version, path)
    return path


def load(root: Path, version: str) -> WeightsVersion:
    path = _weights_dir(root) / f"weights_{version}.json"
    return WeightsVersion.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_latest(root: Path) -> WeightsVersion | None:
    versions = list_versions(root)
    return load(root, versions[-1]) if versions else None


def fit_and_save(incidents: list[dict], fixes: list[str], cfg: dict, root: Path) -> WeightsVersion:
    version = next_version(root)
    wv = fit_weights(incidents, fixes, cfg, version)
    save(root, wv)
    return wv
