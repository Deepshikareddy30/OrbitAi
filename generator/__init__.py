"""Offline world generator (SPEC §3). The only package, besides eval, allowed to touch hidden/."""

import json
from pathlib import Path

import yaml

from . import world as W
from .demo import generate_demo
from .simulate import generate
from .validate import summary

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    with open(path or REPO_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["generator"]


def build(cfg):
    """Return every output file as {relative_path: object}. Pure function of cfg."""
    incidents, root_causes, weights, _ = generate(cfg)
    demo, demo_expected = generate_demo(cfg, incidents[-1]["timestamp"])
    return {
        "data/incidents.json": incidents,
        "data/fixes.json": W.FIXES,
        "data/demo_incidents.json": demo,
        "hidden/root_causes.json": root_causes,
        "hidden/simulator_matrix.json": {"fixes": W.FIX_NAMES, "matrix": W.SIMULATOR_MATRIX},
        "hidden/true_cause_weights.json": {"modifiers": W.HIDDEN_MODIFIERS, "incidents": weights},
        "hidden/demo_expected.json": demo_expected,
    }


def write_dataset(out_root: Path, cfg):
    files = build(cfg)
    for rel, obj in files.items():
        path = out_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return summary(files["data/incidents.json"], files["hidden/root_causes.json"], cfg)
