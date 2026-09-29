"""The five demo-upload incidents (SPEC §8). Same generator, fixed seed, no outcomes."""

from datetime import datetime, timedelta

import numpy as np

from . import world as W
from .simulate import make_context, slack_thread

# Forced context per scenario; symptoms are still sampled by the generator.
SCENARIOS = [
    {"key": "A", "service": "cache-cluster", "env": "prod", "root_cause": "memory_leak",
     "signature": "mem_pressure_oom", "changes": [], "factors": ["resource_limit_low"],
     "scenario": "Close match to many past passes of one fix, no similar failures",
     "expected_verdict": "agree_trust", "focus_fix": "restart_service",
     "expected_top_fix": "restart_service", "expected_gate": "auto_run"},
    {"key": "B", "service": "api-gateway", "env": "prod", "root_cause": "dependency_outage",
     "signature": "timeout_upstream", "changes": [], "factors": ["dependency_degraded"],
     "scenario": "Close match to past failures of the obvious fix",
     "expected_verdict": "agree_dont_trust", "focus_fix": "restart_service",
     "expected_top_fix": "toggle_feature_flag", "expected_gate": None},
    {"key": "C", "service": "workflow-engine", "env": "prod", "root_cause": "bad_deploy",
     "signature": "mem_pressure_oom",
     "changes": [{"type": "deploy", "detail": "v4.8.0", "minutes_before": 12}],
     "factors": ["recent_deploy"],
     "scenario": "Look-alike trap: memory-leak-looking symptoms, but a deploy just before",
     "expected_verdict": "conflict", "focus_fix": "restart_service",
     "expected_top_fix": None, "expected_gate": "human_review"},
    {"key": "D", "service": "message-queue", "env": "staging", "root_cause": "config_error",
     "signature": W.NOVEL_SIGNATURE,
     "changes": [{"type": "config_change", "detail": "message.partitions", "minutes_before": 20}],
     "factors": ["config_change"],
     "scenario": "Novel: service and fault combination never present in training",
     "expected_verdict": "no_evidence", "focus_fix": None,
     "expected_top_fix": None, "expected_gate": "human_review"},
    {"key": "E", "service": "api-gateway", "env": "prod", "root_cause": "connection_exhaustion",
     "signature": "connection_pool_exhausted", "changes": [],
     "factors": ["connection_pool_low", "traffic_spike"],
     "scenario": "Medium-risk fix with borderline trust",
     "expected_verdict": None, "focus_fix": "raise_resource_limits",
     "expected_top_fix": "raise_resource_limits", "expected_gate": "on_call_approval"},
    # The "flagship" single-incident walkthrough incident (2026-09-29 pivot: focused
    # OrbitAI demo spec, not the A-E dashboard walkthrough). billing-service DB timeout
    # right after a connection-pool config deploy - real look-alike tension for the
    # Courtroom (timeout_upstream_db also overlaps db_saturation's signature space, so
    # "database overload" is a real, weak alternate cause, not a contrived one).
    {"key": "FLAGSHIP", "service": "billing-service", "env": "prod", "root_cause": "bad_deploy",
     "signature": "error_rate_5xx",
     "changes": [{"type": "config_change", "detail": "billing.connection_pool_size", "minutes_before": 18}],
     "factors": ["recent_deploy"],
     "scenario": "Flagship: 5xx errors + DB timeouts after a connection-pool config change, high risk -> Courtroom",
     "expected_verdict": None, "focus_fix": "rollback_deploy",
     "expected_top_fix": "rollback_deploy", "expected_gate": None},
]


def generate_demo(cfg, last_timestamp: str):
    rng = np.random.default_rng(cfg["seed"] + 1000)
    t0 = datetime.fromisoformat(last_timestamp.replace("Z", "+00:00")) + timedelta(days=7)
    demo, expected = [], {}
    for i, s in enumerate(SCENARIOS):
        ctx = make_context(rng, cfg, service=s["service"], env=s["env"], root_cause=s["root_cause"],
                           signature=s["signature"], changes=s["changes"], factors=s["factors"])
        iid = f"DEMO-{s['key']}"
        demo.append({
            "id": iid,
            "timestamp": (t0 + timedelta(hours=3 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "service": ctx["service"],
            "environment": ctx["environment"],
            "error_signature": ctx["signature"],
            "symptoms": ctx["symptoms"],
            "changes_before": ctx["changes"],
            "slack_thread": slack_thread(ctx["service"], ctx["environment"], ctx["signature"],
                                         ctx["symptoms"], ctx["changes"], []),
            "attempts": [],
            "contributing_factors": ctx["visible_factors"],
            "postmortem_note": None,
            "split": "demo",
        })
        p = {f: v["p_success"] for f, v in ctx["breakdown"].items()}
        expected[iid] = {
            "scenario": s["scenario"],
            "expected_verdict": s["expected_verdict"],
            "focus_fix": s["focus_fix"],
            "expected_top_fix": s["expected_top_fix"],
            "expected_gate": s["expected_gate"],
            "root_cause": ctx["root_cause"],
            "true_factors": ctx["true_factors"],
            "best_fix": max(p, key=p.get),
            "p_success": p,
            "breakdown": ctx["breakdown"],
        }
    return demo, expected
