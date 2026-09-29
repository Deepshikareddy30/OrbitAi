"""Shared application state: loaded dataset, config, MemoryStore, weights root, audit log.

Never reads the ground-truth folder - see tests/test_hidden_leak.py. All hidden lookups
happen inside simworld, which returns only plain, already-safe results.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.weights import fit_and_save, load_latest
from memory import DEFAULT_BANK_ID, get_store
from memory.loader import retain_all_train

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class AppState:
    incidents: list[dict]
    incidents_by_id: dict[str, dict]
    demo_incidents: list[dict]
    fixes_catalog: list[dict]
    engine_cfg: dict
    gate_cfg: dict
    store: "object"
    bank_id: str
    weights_root: Path
    audit_log: list[dict] = field(default_factory=list)

    @property
    def fix_names(self) -> list[str]:
        return [f["fix"] for f in self.fixes_catalog]

    @property
    def recall_top_n(self) -> int:
        """SPEC recall_top_n=30 is tuned for real Hindsight's semantic+keyword+graph
        retrieval. The InMemoryStore fake's naive keyword-overlap recall is measurably
        weaker at that width (docs/DECISIONS.md EVAL2 - it can miss a strong candidate
        entirely) - widen the net for the fake so the demo shows evidence quality
        consistent with the eval numbers, not an artifact of the toy retrieval stand-in.
        """
        using_real_hindsight = type(self.store).__module__.endswith("hindsight_store")
        if using_real_hindsight:
            return self.engine_cfg["recall_top_n"]
        return min(200, len(self.incidents))

    def log_event(self, event: str, **fields) -> dict:
        entry = {"event": event, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), **fields}
        self.audit_log.append(entry)
        return entry

    def find(self, incident_id: str) -> dict | None:
        return self.incidents_by_id.get(incident_id)

    def current_weights(self):
        wv = load_latest(self.weights_root)
        if wv is None:
            wv = fit_and_save(self.incidents, self.fix_names, self.engine_cfg, self.weights_root)
            self.log_event("weights_refit", version=wv.version, reason="initial fit")
        return wv


def build_default_state(*, memory_kind: str | None = None, weights_root: Path | None = None,
                        bank_id: str | None = None) -> AppState:
    incidents = json.loads((REPO_ROOT / "data" / "incidents.json").read_text(encoding="utf-8"))
    demo_incidents = json.loads((REPO_ROOT / "data" / "demo_incidents.json").read_text(encoding="utf-8"))
    fixes_catalog = json.loads((REPO_ROOT / "data" / "fixes.json").read_text(encoding="utf-8"))
    engine_cfg = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["engine"]
    gate_cfg = yaml.safe_load((REPO_ROOT / "gate_config.yaml").read_text())

    # Defaults to the in-memory fake so `uvicorn api.app:app` boots without Hindsight
    # credentials; set MEMORY_STORE=hindsight (with HINDSIGHT_API_KEY) for the real thing.
    kind = memory_kind or os.environ.get("MEMORY_STORE", "fake")
    store = get_store(kind)
    bank_id = bank_id or os.environ.get("HINDSIGHT_BANK_ID", DEFAULT_BANK_ID)
    weights_root = weights_root or REPO_ROOT

    state = AppState(
        incidents=incidents, incidents_by_id={i["id"]: i for i in incidents},
        demo_incidents=demo_incidents, fixes_catalog=fixes_catalog, engine_cfg=engine_cfg,
        gate_cfg=gate_cfg, store=store, bank_id=bank_id, weights_root=weights_root,
    )

    n = retain_all_train(store, bank_id, incidents)
    state.log_event("memory_retained", incident_id=None, count=n, note="startup bulk load")
    state.current_weights()  # ensure at least v1 exists
    return state


def reset_state(state: AppState) -> None:
    """SPEC S10.7 demo reset: rebuild memory from the training snapshot. Reloads
    incidents.json fresh from disk so any splits flipped by the feedback loop
    (demo/held_out -> train) and any appended attempts are discarded.
    """
    fresh = json.loads((REPO_ROOT / "data" / "incidents.json").read_text(encoding="utf-8"))
    state.incidents = fresh
    state.incidents_by_id = {i["id"]: i for i in fresh}
    state.demo_incidents = json.loads((REPO_ROOT / "data" / "demo_incidents.json").read_text(encoding="utf-8"))

    state.store.reset(state.bank_id)
    n = retain_all_train(state.store, state.bank_id, state.incidents)
    state.audit_log.clear()
    state.log_event("memory_retained", incident_id=None, count=n, note="demo reset")

    weights_dir = state.weights_root / "weights"
    if weights_dir.exists():
        for p in weights_dir.glob("weights_v*.json"):
            p.unlink()
    state.current_weights()
