"""Milestone 3 tests: feature building and reflection (SPEC S5.1, S5.2)."""

import json
import shutil

import pytest

from engine import features as F
from engine.weights import fit_and_save, list_versions, load, load_latest, next_version
from generator import REPO_ROOT, load_config


@pytest.fixture(scope="module")
def incidents():
    return json.loads((REPO_ROOT / "data" / "incidents.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixes():
    return [f["fix"] for f in json.loads((REPO_ROOT / "data" / "fixes.json").read_text(encoding="utf-8"))]


@pytest.fixture(scope="module")
def engine_cfg():
    import yaml
    return yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["engine"]


# -- features ---------------------------------------------------------------

def test_bands_are_tertiles_and_cover_range(incidents):
    train = [i for i in incidents if i["split"] == "train"]
    bands = F.fit_bands(train)
    for field in F.SYMPTOM_FIELDS:
        lo, hi = bands.cutpoints[field]
        assert lo <= hi
    counts = {b: 0 for b in F.BANDS}
    for i in train:
        counts[bands.band("p99_ms", i["symptoms"]["p99_ms"])] += 1
    assert all(c > 0 for c in counts.values())


def test_feature_dims_are_one_hot_and_multi_hot():
    from generator import world as W
    bands = F.fit_bands([{"symptoms": {"p99_ms": 1000, "error_rate": 0.05, "cpu": 0.5, "mem": 0.5}}] * 3)
    inc = {"service": "billing-service", "environment": "prod", "error_signature": "timeout_upstream_db",
          "symptoms": {"p99_ms": 1000, "error_rate": 0.05, "cpu": 0.5, "mem": 0.5},
          "changes_before": [{"type": "deploy", "detail": "v1", "minutes_before": 5}],
          "contributing_factors": ["recent_deploy", "traffic_spike"]}
    dims = F.feature_dims(inc, bands)
    assert dims["service=billing-service"] == 1.0
    assert dims["change_types=deploy"] == 1.0
    assert dims["factors=recent_deploy"] == 1.0
    assert dims["factors=traffic_spike"] == 1.0
    assert len(dims) == 10  # 7 categorical/band groups + 1 change_type + 2 factors
    for rc in W.ROOT_CAUSES:
        assert not any(rc in d for d in dims)


def test_match_exact_and_jaccard():
    bands = F.fit_bands([{"symptoms": {"p99_ms": 1, "error_rate": 0.01, "cpu": 0.1, "mem": 0.1}}])
    a = {"service": "x", "change_types": {"deploy"}, "factors": {"recent_deploy", "traffic_spike"}}
    b = {"service": "x", "change_types": {"deploy"}, "factors": {"recent_deploy"}}
    c = {"service": "y", "change_types": set(), "factors": set()}
    assert F.match("service", a, b) == 1.0
    assert F.match("service", a, c) == 0.0
    assert F.match("factors", a, b) == pytest.approx(0.5)  # 1 shared / 2 union
    assert F.match("change_types", a, c) == 0.0  # one empty, one not -> 0
    assert F.match("factors", c, c) == 1.0  # both empty -> vacuously matching


# -- reflection / weights ----------------------------------------------------

def test_fit_weights_importance_sums_to_one_with_floor(incidents, fixes, engine_cfg):
    from engine.weights import fit_weights
    wv = fit_weights(incidents, fixes, engine_cfg, "vtest")
    for fix, fw in wv.per_fix.items():
        total = sum(fw.importance.values())
        assert total == pytest.approx(1.0, abs=1e-3)  # values are stored rounded to 5dp
        min_floor = engine_cfg["importance_floor"] / len(wv.all_dims) - 1e-9
        assert all(v >= min_floor for v in fw.importance.values())
        group_total = sum(fw.group_importance.values())
        assert group_total == pytest.approx(1.0, abs=1e-3)


def test_shrinkage_low_n_leans_on_global(incidents, fixes, engine_cfg):
    from engine.weights import fit_weights
    wv = fit_weights(incidents, fixes, engine_cfg, "vtest")
    rare_fix = min(wv.per_fix, key=lambda f: wv.per_fix[f].n_train)
    fw = wv.per_fix[rare_fix]
    assert fw.lambda_k < 0.5  # few samples -> lambda close to 0 -> leans global
    common_fix = max(wv.per_fix, key=lambda f: wv.per_fix[f].n_train)
    assert wv.per_fix[common_fix].lambda_k > fw.lambda_k


def test_weight_recovery_recovers_known_hidden_modifier(incidents, fixes, engine_cfg):
    """The simulator's hidden HIDDEN_MODIFIERS['recent_deploy']['restart_service'] = -1.2
    should be recoverable (right sign, similar magnitude) from noisy outcomes alone.
    This test lives with the other generator/engine tests (not eval/) but is exactly
    the sanity check SPEC S10.3's 'weight_recovery' aggregate formalizes later.
    """
    from engine.weights import fit_weights
    from generator import world as W  # generator package may read hidden ground truth

    wv = fit_weights(incidents, fixes, engine_cfg, "vtest")
    learned = wv.per_fix["restart_service"].local_coef.get("factors=recent_deploy")
    hidden_truth = W.HIDDEN_MODIFIERS["recent_deploy"]["restart_service"]
    assert learned is not None
    assert learned < 0  # same sign as hidden truth (-1.2)
    assert abs(learned - hidden_truth) < 1.5  # same ballpark, not exact (noisy outcomes)


def test_versioning_increments_and_round_trips(tmp_path, incidents, fixes, engine_cfg):
    assert next_version(tmp_path) == "v1"
    wv1 = fit_and_save(incidents, fixes, engine_cfg, tmp_path)
    assert wv1.version == "v1"
    assert next_version(tmp_path) == "v2"
    wv2 = fit_and_save(incidents, fixes, engine_cfg, tmp_path)
    assert wv2.version == "v2"
    assert list_versions(tmp_path) == ["v1", "v2"]

    loaded = load(tmp_path, "v1")
    assert loaded.version == "v1"
    assert loaded.per_fix.keys() == wv1.per_fix.keys()
    assert load_latest(tmp_path).version == "v2"


def test_load_latest_none_when_no_versions(tmp_path):
    assert load_latest(tmp_path) is None


def test_reproducible_fit(incidents, fixes, engine_cfg):
    from engine.weights import fit_weights
    a = fit_weights(incidents, fixes, engine_cfg, "va")
    b = fit_weights(incidents, fixes, engine_cfg, "vb")
    for fix in fixes:
        assert a.per_fix[fix].importance == b.per_fix[fix].importance
