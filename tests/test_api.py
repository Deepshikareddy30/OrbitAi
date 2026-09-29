"""Milestone 7 (backend half): API routes, wired end to end against the fake store and
a temp weights dir - no real Hindsight/network needed.
"""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.app import create_app
from api.state import AppState
from generator import REPO_ROOT
from memory import DEFAULT_BANK_ID
from memory.fake_store import InMemoryStore
from memory.loader import retain_all_train


@pytest.fixture()
def client(tmp_path):
    incidents = json.loads((REPO_ROOT / "data" / "incidents.json").read_text())
    demo_incidents = json.loads((REPO_ROOT / "data" / "demo_incidents.json").read_text())
    fixes_catalog = json.loads((REPO_ROOT / "data" / "fixes.json").read_text())
    engine_cfg = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["engine"]
    gate_cfg = yaml.safe_load((REPO_ROOT / "gate_config.yaml").read_text())
    store = InMemoryStore()
    state = AppState(incidents=incidents, incidents_by_id={i["id"]: i for i in incidents},
                     demo_incidents=demo_incidents, fixes_catalog=fixes_catalog, engine_cfg=engine_cfg,
                     gate_cfg=gate_cfg, store=store, bank_id=DEFAULT_BANK_ID, weights_root=tmp_path)
    retain_all_train(store, DEFAULT_BANK_ID, incidents)
    state.current_weights()

    app = create_app(state=state)
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_fixes_catalog(client):
    r = client.get("/api/fixes")
    assert r.status_code == 200
    assert {f["fix"] for f in r.json()} >= {"restart_service", "db_failover"}


def test_list_incidents_filtered_by_split(client):
    r = client.get("/api/incidents", params={"split": "held_out"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    assert all(i["split"] == "held_out" for i in body["incidents"])


def test_list_incidents_count_reflects_full_total_not_page_size(client):
    """SPEC: dataset is ~300 incidents; the default limit=100 must not make `count`
    (used by the UI's stat tiles) look like there are only 100."""
    r = client.get("/api/incidents").json()
    assert r["count"] > 100
    assert len(r["incidents"]) == 100  # still page-capped


def test_list_incidents_pagination_offset(client):
    page1 = client.get("/api/incidents", params={"limit": 10, "offset": 0}).json()
    page2 = client.get("/api/incidents", params={"limit": 10, "offset": 10}).json()
    assert page1["incidents"][0]["id"] != page2["incidents"][0]["id"]
    assert {i["id"] for i in page1["incidents"]}.isdisjoint({i["id"] for i in page2["incidents"]})


def test_get_incident_by_id(client):
    r = client.get("/api/incidents/INC-0001")
    assert r.status_code == 200
    assert r.json()["id"] == "INC-0001"


def test_get_unknown_incident_404(client):
    assert client.get("/api/incidents/NOPE").status_code == 404


def test_demo_incidents_listed(client):
    r = client.get("/api/demo/incidents")
    ids = {d["id"] for d in r.json()}
    assert ids == {"DEMO-A", "DEMO-B", "DEMO-C", "DEMO-D", "DEMO-E", "DEMO-FLAGSHIP"}


def test_recommendation_no_hidden_leak_in_response(client):
    r = client.get("/api/incidents/DEMO-A/recommendation")
    assert r.status_code == 200
    body = r.json()
    text = json.dumps(body)
    assert "root_cause" not in text and "p_success" not in text
    assert body["ranked_fixes"], "expected at least one ranked fix"
    top = body["ranked_fixes"][0]
    assert "trust" in top["evidence"] and "action" in top["gate"]


def test_recommendation_includes_gate_decision_per_fix(client):
    r = client.get("/api/incidents/DEMO-C/recommendation").json()
    for entry in r["ranked_fixes"]:
        assert entry["gate"]["action"] in ("auto_run", "one_click", "escalate_ic", "two_person")


def test_execute_demo_a_accepts_and_refits(client):
    r = client.post("/api/incidents/DEMO-A/execute", json={"fix": "restart_service"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] in ("resolved", "failed", "recurred")
    # weights version should now exist beyond v1 if accepted, or stay v1 if rejected -
    # either way the call must succeed and be reflected in the audit log
    audit = client.get("/api/audit").json()
    assert any(e["event"] == "recommendation_verified" for e in audit["events"])


def test_execute_unknown_incident_404(client):
    r = client.post("/api/incidents/NOPE/execute", json={"fix": "restart_service"})
    assert r.status_code == 404


def test_poison_endpoint_is_blocked_and_audited(client):
    r = client.post("/api/incidents/DEMO-B/poison",
                    json={"fix": "db_failover", "outcome": "resolved", "verified": False})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False

    audit = client.get("/api/audit", params={"event": "memory_write_blocked"}).json()
    assert audit["count"] >= 1


def test_weights_versions_and_fetch(client):
    versions = client.get("/api/weights/versions").json()["versions"]
    assert "v1" in versions
    wv = client.get(f"/api/weights/{versions[-1]}").json()
    assert "per_fix" in wv and "restart_service" in wv["per_fix"]


def test_weights_unknown_version_404(client):
    assert client.get("/api/weights/v999").status_code == 404


def test_gate_config_exposed(client):
    r = client.get("/api/gate/config").json()
    assert "risk_rules" in r and "low" in r["risk_rules"]


def test_eval_results_served_as_is(client):
    r = client.get("/api/eval/results")
    assert r.status_code == 200
    body = r.json()
    assert "meta" in body and "aggregates" in body and "incidents" in body


def test_demo_reset_restores_clean_state(client):
    client.post("/api/incidents/DEMO-A/execute", json={"fix": "restart_service"})
    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    audit = client.get("/api/audit").json()
    assert not any(e["event"] == "recommendation_verified" for e in audit["events"])
