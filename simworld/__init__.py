"""The simulated production environment's boundary. Exactly like a real system's API
layer never sees inside its actual infrastructure, api/ never reads hidden/ - it only
calls simworld.run_fix() and gets back a plain FeedbackResult with no hidden fields.

This package (alongside generator/ and eval/) is explicitly allowed to read hidden/ -
see tests/test_hidden_leak.py, which forbids it only for engine/memory/api/ui/feedback.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from engine.weights import load_latest
from feedback.loop import FeedbackResult, apply_outcome
from generator import REPO_ROOT, load_config
from generator.executor import execute_fix
from memory.base import MemoryStore

log = logging.getLogger("simworld")


def _load_hidden_truth(incident_id: str) -> tuple[str, set]:
    """Look up (root_cause, true_factors) for an incident, checking hidden/root_causes.json
    (train/held_out incidents) then hidden/demo_expected.json (demo incidents)."""
    root_causes = json.loads((REPO_ROOT / "hidden" / "root_causes.json").read_text())
    if incident_id in root_causes:
        r = root_causes[incident_id]
        return r["root_cause"], set(r["true_factors"])
    demo = json.loads((REPO_ROOT / "hidden" / "demo_expected.json").read_text())
    if incident_id in demo:
        d = demo[incident_id]
        return d["root_cause"], set(d["true_factors"])
    raise KeyError(f"No hidden ground truth for incident {incident_id!r}")


def run_fix(incident: dict, fix: str, *, writer: str, authorized: bool,
           store: MemoryStore, bank_id: str, incidents: list[dict], fixes: list[str],
           engine_cfg: dict, weights_root: Path = REPO_ROOT, rng: Optional[np.random.Generator] = None,
           human_override: bool = False, override_reason: str = None) -> FeedbackResult:
    """Execute `fix` against `incident`'s (hidden) true root cause, then run it through
    the feedback loop (SPEC S7). This is the only function api/ calls to make something
    happen in the simulated world.
    """
    root_cause, true_factors = _load_hidden_truth(incident["id"])
    gen_cfg = load_config()
    rng = rng or np.random.default_rng()
    attempt, _hidden_debug = execute_fix(root_cause, true_factors, incident["changes_before"], fix,
                                         gen_cfg, rng, human_override=human_override,
                                         override_reason=override_reason)
    return apply_outcome(incident, attempt, writer=writer, authorized=authorized, store=store,
                         bank_id=bank_id, incidents=incidents, fixes=fixes, cfg=engine_cfg,
                         weights_root=weights_root)


def poison_attempt(incident: dict, fix: str, outcome: str, *, writer: str, authorized: bool,
                   verified: bool, store: MemoryStore, bank_id: str, incidents: list[dict],
                   fixes: list[str], engine_cfg: dict, weights_root: Path = REPO_ROOT) -> FeedbackResult:
    """For the poisoning-guard demo (SPEC S7): inject a fabricated claim, bypassing the
    simulator entirely, to show it gets stored-but-blocked regardless of what it claims.
    """
    attempt = {"fix": fix, "outcome": outcome, "time_to_recover_min": 1 if outcome != "failed" else None,
              "recurred_within_24h": False, "verified": verified, "human_override": False,
              "override_reason": "poisoning-guard demo"}
    return apply_outcome(incident, attempt, writer=writer, authorized=authorized, store=store,
                         bank_id=bank_id, incidents=incidents, fixes=fixes, cfg=engine_cfg,
                         weights_root=weights_root)
