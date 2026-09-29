"""Milestone 1 validation: reproducibility, schema, split, look-alike structure,
novelty withholding, and the hidden-fields-not-leaked-into-visible-data check.
"""

import json

import pytest

from generator import REPO_ROOT, build, load_config
from generator import world as W

CFG = load_config()


@pytest.fixture(scope="module")
def files():
    return build(CFG)


@pytest.fixture(scope="module")
def incidents(files):
    return files["data/incidents.json"]


@pytest.fixture(scope="module")
def root_causes(files):
    return files["hidden/root_causes.json"]


def test_reproducible_with_fixed_seed():
    a = build(CFG)
    b = build(CFG)
    assert a["data/incidents.json"] == b["data/incidents.json"]
    assert a["hidden/root_causes.json"] == b["hidden/root_causes.json"]


def test_reproducible_across_process_hash_seeds(tmp_path):
    """In-process re-runs share one PYTHONHASHSEED and can't catch bugs where output
    depends on Python's (per-process, randomized-by-default) set iteration order - see
    docs/DECISIONS.md G6. This actually spawns two subprocesses with different hash seeds.
    """
    import os
    import subprocess
    import sys

    def run(out_dir, hash_seed):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        subprocess.run([sys.executable, "-m", "generator", "--out", str(out_dir)],
                       cwd=REPO_ROOT, env=env, check=True, capture_output=True, text=True)

    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    run(out1, "1")
    run(out2, "12345")
    for rel in ["data/incidents.json", "data/demo_incidents.json", "hidden/root_causes.json"]:
        assert (out1 / rel).read_text() == (out2 / rel).read_text(), f"{rel} differs across hash seeds"


def test_incident_count_and_split(incidents):
    assert len(incidents) == CFG["n_incidents"]
    n_held = sum(1 for i in incidents if i["split"] == "held_out")
    frac = n_held / len(incidents)
    assert abs(frac - CFG["held_out_fraction"]) < 0.05
    # time-ordered: train incidents are all older than held_out incidents
    times = [i["timestamp"] for i in incidents]
    assert times == sorted(times)
    last_train = max(i["timestamp"] for i in incidents if i["split"] == "train")
    first_held = min(i["timestamp"] for i in incidents if i["split"] == "held_out")
    assert last_train <= first_held


def test_ids_unique_and_ordered(incidents):
    ids = [i["id"] for i in incidents]
    assert len(ids) == len(set(ids))
    assert ids == [f"INC-{n + 1:04d}" for n in range(len(ids))]


REQUIRED_FIELDS = {"id", "timestamp", "service", "environment", "error_signature", "symptoms",
                   "changes_before", "slack_thread", "attempts", "contributing_factors",
                   "postmortem_note", "split"}


def test_schema(incidents):
    for inc in incidents:
        assert REQUIRED_FIELDS <= inc.keys()
        assert inc["service"] in W.SERVICES
        assert inc["environment"] in W.ENVIRONMENTS
        assert set(inc["symptoms"]) == {"p99_ms", "error_rate", "cpu", "mem"}
        assert set(inc["contributing_factors"]) <= set(W.FACTOR_VOCAB)
        assert inc["split"] in {"train", "held_out"}
        assert len(inc["attempts"]) >= 1
        for a in inc["attempts"]:
            assert a["fix"] in W.FIX_NAMES
            assert a["outcome"] in {"resolved", "failed", "recurred"}
            assert isinstance(a["verified"], bool)
            if a["outcome"] in {"resolved", "recurred"}:
                assert a["time_to_recover_min"] is not None
            else:
                assert a["time_to_recover_min"] is None


def test_never_marks_success_from_click_alone(incidents):
    """An unverified 'resolved' exists (SPEC: don't confuse click-resolved with real recovery)."""
    unverified_resolved = [a for i in incidents for a in i["attempts"]
                           if a["outcome"] == "resolved" and not a["verified"]]
    assert len(unverified_resolved) > 0


def test_postmortem_never_names_hidden_root_cause(incidents):
    """DECISIONS G1: narrative text must not leak ground truth."""
    for inc in incidents:
        text = (inc["postmortem_note"] or "") + " ".join(inc["slack_thread"])
        for rc in W.ROOT_CAUSES:
            assert rc not in text
            assert rc.replace("_", " ") not in text


def test_lookalike_structure_present(incidents, root_causes):
    from generator.validate import lookalike_counts
    counts = lookalike_counts(incidents, root_causes, split="train")
    assert counts["leak_like_restart_resolved"] >= 10
    assert counts["deploy_then_restart_failed"] >= 10


def test_withheld_combo_absent_everywhere(incidents, root_causes):
    combo = (CFG["withheld_combo"]["service"], CFG["withheld_combo"]["root_cause"])
    for inc in incidents:
        assert (inc["service"], root_causes[inc["id"]]["root_cause"]) != combo
    assert not any(i["error_signature"] == W.NOVEL_SIGNATURE for i in incidents)


def test_demo_incidents_not_in_training(files):
    from generator.demo import SCENARIOS

    demo = files["data/demo_incidents.json"]
    train_ids = {i["id"] for i in files["data/incidents.json"]}
    assert {d["id"] for d in demo}.isdisjoint(train_ids)
    assert len(demo) == len(SCENARIOS)
    for d in demo:
        assert d["attempts"] == []
        assert d["split"] == "demo"


def test_demo_scenario_d_is_the_withheld_combo(files):
    demo = files["data/demo_incidents.json"]
    d = next(x for x in demo if x["id"] == "DEMO-D")
    assert d["service"] == CFG["withheld_combo"]["service"]
    assert d["error_signature"] == W.NOVEL_SIGNATURE


def test_demo_scenario_c_is_lookalike_trap(files):
    demo = files["data/demo_incidents.json"]
    expected = files["hidden/demo_expected.json"]
    c = next(x for x in demo if x["id"] == "DEMO-C")
    assert c["error_signature"] == "mem_pressure_oom"
    assert any(ch["type"] == "deploy" for ch in c["changes_before"])
    assert expected["DEMO-C"]["root_cause"] == "bad_deploy"
    assert expected["DEMO-C"]["expected_verdict"] == "conflict"


def test_hidden_files_have_no_extra_visible_leak(files):
    """hidden/*.json are internally consistent and keyed by real incident ids."""
    ids = {i["id"] for i in files["data/incidents.json"]}
    assert set(files["hidden/root_causes.json"]) == ids
    assert set(files["hidden/true_cause_weights.json"]["incidents"]) == ids
    for rc in files["hidden/root_causes.json"].values():
        assert rc["root_cause"] in W.ROOT_CAUSES


def test_fixes_catalog(files):
    fixes = files["data/fixes.json"]
    names = {f["fix"] for f in fixes}
    assert names == set(W.FIX_NAMES)
    assert {f["risk_tier"] for f in fixes} <= {"low", "medium", "high"}


def test_written_files_are_valid_json(tmp_path):
    from generator import write_dataset
    stats = write_dataset(tmp_path, CFG)
    assert stats["incidents"] == CFG["n_incidents"]
    for rel in ["data/incidents.json", "data/fixes.json", "data/demo_incidents.json",
               "hidden/root_causes.json", "hidden/simulator_matrix.json",
               "hidden/true_cause_weights.json", "hidden/demo_expected.json"]:
        assert json.loads((tmp_path / rel).read_text(encoding="utf-8"))
