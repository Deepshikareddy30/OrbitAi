"""Static definition of the simulated SaaS world (SPEC §3.1, §3.2, §3.5).

Everything in this module that describes root causes, the simulator matrix or hidden
modifiers is ground truth. It is written to hidden/ and must never be imported by
engine/, memory/, api/ or ui/.
"""

SERVICES = [
    "api-gateway", "auth-service", "tenant-service", "billing-service", "workflow-engine",
    "notification-service", "search-service", "primary-db", "cache-cluster", "message-queue",
]

# Relative incident frequency per service.
SERVICE_WEIGHTS = {
    "api-gateway": 1.3, "auth-service": 1.1, "tenant-service": 1.0, "billing-service": 1.3,
    "workflow-engine": 1.7, "notification-service": 1.0, "search-service": 1.0,
    "primary-db": 1.0, "cache-cluster": 0.9, "message-queue": 0.7,
}

ENVIRONMENTS = {"prod": 0.6, "staging": 0.25, "canary": 0.15}

ROOT_CAUSES = [
    "cpu_saturation", "memory_leak", "disk_full", "network_latency", "packet_loss",
    "connection_exhaustion", "bad_deploy", "config_error", "db_saturation",
    "dependency_outage", "cache_stampede",
]

# Root causes that only happen when a change preceded the incident.
CHANGE_DRIVEN = {"bad_deploy", "config_error"}
CHANGE_BOOST = 5.0

# Prior weight of each root cause per service.
SERVICE_FAULTS = {
    "api-gateway": {"network_latency": 3, "packet_loss": 3, "connection_exhaustion": 2,
                    "cpu_saturation": 2, "dependency_outage": 4, "bad_deploy": 2, "config_error": 2},
    "auth-service": {"memory_leak": 3, "cpu_saturation": 2, "dependency_outage": 2,
                     "cache_stampede": 2, "bad_deploy": 3, "config_error": 2},
    "tenant-service": {"memory_leak": 3, "db_saturation": 2, "connection_exhaustion": 2,
                       "bad_deploy": 3, "config_error": 2},
    "billing-service": {"db_saturation": 3, "connection_exhaustion": 4, "dependency_outage": 3,
                        "memory_leak": 2, "bad_deploy": 3, "config_error": 1},
    "workflow-engine": {"memory_leak": 7, "cpu_saturation": 2, "disk_full": 1,
                        "connection_exhaustion": 1, "bad_deploy": 6, "config_error": 1},
    "notification-service": {"dependency_outage": 4, "memory_leak": 2, "network_latency": 2,
                             "bad_deploy": 2, "config_error": 2},
    "search-service": {"cpu_saturation": 3, "memory_leak": 3, "disk_full": 2,
                       "cache_stampede": 2, "bad_deploy": 2},
    "primary-db": {"db_saturation": 5, "disk_full": 3, "connection_exhaustion": 3,
                   "cpu_saturation": 2, "config_error": 1},
    "cache-cluster": {"cache_stampede": 4, "memory_leak": 2, "network_latency": 2,
                      "packet_loss": 2, "config_error": 1},
    "message-queue": {"disk_full": 3, "connection_exhaustion": 2, "network_latency": 2,
                      "memory_leak": 2, "config_error": 1},
}

# Visible error signature distribution per root cause. Overlap is deliberate (look-alikes):
# e.g. bad_deploy often presents as mem_pressure_oom, exactly like memory_leak.
SIGNATURES = {
    "memory_leak": {"mem_pressure_oom": 0.7, "latency_degradation": 0.15, "pod_restarts": 0.15},
    "bad_deploy": {"mem_pressure_oom": 0.35, "error_rate_5xx": 0.3, "latency_degradation": 0.15,
                   "pod_restarts": 0.2},
    "cpu_saturation": {"cpu_throttling": 0.6, "latency_degradation": 0.4},
    "disk_full": {"disk_pressure": 0.6, "write_failures": 0.4},
    "network_latency": {"latency_degradation": 0.5, "timeout_upstream": 0.5},
    "packet_loss": {"timeout_upstream": 0.4, "error_rate_5xx": 0.3, "connection_resets": 0.3},
    "connection_exhaustion": {"connection_pool_exhausted": 0.65, "timeout_upstream_db": 0.35},
    "config_error": {"error_rate_5xx": 0.6, "startup_failure": 0.4},
    "db_saturation": {"timeout_upstream_db": 0.6, "latency_degradation": 0.4},
    "dependency_outage": {"timeout_upstream": 0.6, "error_rate_5xx": 0.4},
    "cache_stampede": {"latency_degradation": 0.35, "cache_miss_storm": 0.45, "cpu_throttling": 0.2},
}
# Look-alike trap (SPEC §3.5): on memory-heavy services a bad deploy usually looks like a leak.
LEAK_PRONE_SERVICES = {"workflow-engine", "auth-service", "tenant-service", "search-service"}
SIGNATURE_OVERRIDES = {
    ("bad_deploy", "leak_prone"): {"mem_pressure_oom": 0.65, "pod_restarts": 0.2, "error_rate_5xx": 0.15},
}

# Signature that only the withheld (novel) combination produces.
NOVEL_SIGNATURE = "consumer_rebalance_storm"

# Typical symptoms per visible signature: p99_ms, error_rate, cpu, mem.
SIGNATURE_PROFILE = {
    "mem_pressure_oom": (1400, 0.04, 0.55, 0.93),
    "latency_degradation": (2600, 0.03, 0.60, 0.60),
    "pod_restarts": (900, 0.08, 0.50, 0.80),
    "error_rate_5xx": (800, 0.15, 0.45, 0.50),
    "cpu_throttling": (2200, 0.03, 0.95, 0.55),
    "disk_pressure": (1200, 0.05, 0.40, 0.50),
    "write_failures": (900, 0.12, 0.35, 0.50),
    "timeout_upstream": (5000, 0.09, 0.35, 0.45),
    "connection_resets": (1800, 0.10, 0.40, 0.45),
    "connection_pool_exhausted": (4200, 0.08, 0.50, 0.60),
    "timeout_upstream_db": (4800, 0.07, 0.45, 0.55),
    "startup_failure": (600, 0.30, 0.20, 0.30),
    "cache_miss_storm": (2400, 0.04, 0.80, 0.50),
    "consumer_rebalance_storm": (3500, 0.06, 0.70, 0.50),
}

SIGNATURE_TEXT = {
    "mem_pressure_oom": "memory pressure / OOM kills",
    "latency_degradation": "p99 latency degradation",
    "pod_restarts": "pods restarting",
    "error_rate_5xx": "5xx error spike",
    "cpu_throttling": "CPU throttling",
    "disk_pressure": "disk pressure",
    "write_failures": "write failures",
    "timeout_upstream": "upstream timeouts",
    "connection_resets": "connection resets",
    "connection_pool_exhausted": "connection pool exhausted",
    "timeout_upstream_db": "DB timeouts",
    "startup_failure": "startup failures",
    "cache_miss_storm": "cache miss storm",
    "consumer_rebalance_storm": "consumer rebalance storm",
}

FIXES = [
    {"fix": "restart_service", "risk_tier": "low", "reversible": "yes", "typical_ttr_min": 5,
     "description": "Rolling restart of the affected service's pods."},
    {"fix": "scale_out", "risk_tier": "low", "reversible": "yes", "typical_ttr_min": 8,
     "description": "Add replicas / capacity to the affected service."},
    {"fix": "toggle_feature_flag", "risk_tier": "low", "reversible": "yes", "typical_ttr_min": 4,
     "description": "Disable the feature path or dependency behind a flag."},
    {"fix": "clear_cache", "risk_tier": "low", "reversible": "yes", "typical_ttr_min": 6,
     "description": "Flush and re-warm the relevant cache keys."},
    {"fix": "rollback_deploy", "risk_tier": "medium", "reversible": "mostly", "typical_ttr_min": 12,
     "description": "Roll back the most recent deploy or config change."},
    {"fix": "raise_resource_limits", "risk_tier": "medium", "reversible": "yes", "typical_ttr_min": 15,
     "description": "Raise memory/CPU limits or connection pool size."},
    {"fix": "drain_node", "risk_tier": "medium", "reversible": "mostly", "typical_ttr_min": 20,
     "description": "Cordon and drain the unhealthy node(s)."},
    {"fix": "db_failover", "risk_tier": "high", "reversible": "no", "typical_ttr_min": 25,
     "description": "Fail the primary database over to a replica."},
]
FIX_NAMES = [f["fix"] for f in FIXES]
FIX_BY_NAME = {f["fix"]: f for f in FIXES}

# HIDDEN: base success probability for each (root cause x fix), in FIX_NAMES order.
_MATRIX_ROWS = {
    #                       restart scale  flag   cache  rollbk raise  drain  failover
    "cpu_saturation":        (0.30, 0.85, 0.10, 0.10, 0.15, 0.60, 0.30, 0.05),
    "memory_leak":           (0.85, 0.30, 0.05, 0.05, 0.20, 0.60, 0.35, 0.03),
    "disk_full":             (0.15, 0.10, 0.03, 0.15, 0.05, 0.30, 0.75, 0.20),
    "network_latency":       (0.15, 0.25, 0.20, 0.05, 0.10, 0.05, 0.55, 0.10),
    "packet_loss":           (0.10, 0.15, 0.10, 0.03, 0.05, 0.03, 0.70, 0.05),
    "connection_exhaustion": (0.45, 0.40, 0.10, 0.05, 0.10, 0.70, 0.10, 0.15),
    "bad_deploy":            (0.15, 0.10, 0.35, 0.05, 0.90, 0.10, 0.05, 0.02),
    "config_error":          (0.10, 0.05, 0.70, 0.05, 0.60, 0.10, 0.03, 0.02),
    "db_saturation":         (0.10, 0.35, 0.15, 0.25, 0.05, 0.30, 0.05, 0.80),
    "dependency_outage":     (0.15, 0.10, 0.75, 0.10, 0.05, 0.05, 0.05, 0.05),
    "cache_stampede":        (0.20, 0.60, 0.30, 0.15, 0.05, 0.20, 0.05, 0.05),
}
SIMULATOR_MATRIX = {rc: dict(zip(FIX_NAMES, row)) for rc, row in _MATRIX_ROWS.items()}

FACTOR_VOCAB = [
    "recent_deploy", "config_change", "infra_change", "traffic_spike", "dependency_degraded",
    "resource_limit_low", "connection_pool_low", "cache_cold", "disk_usage_high",
    "feature_flag_change", "version_upgrade", "schema_migration",
]

# HIDDEN: true factors a root cause brings with it (factor -> probability).
ROOT_FACTORS = {
    "cpu_saturation": {"traffic_spike": 0.6, "resource_limit_low": 0.4},
    "memory_leak": {"resource_limit_low": 0.5},
    "disk_full": {"disk_usage_high": 0.9},
    "network_latency": {"infra_change": 0.4, "dependency_degraded": 0.4},
    "packet_loss": {"infra_change": 0.6},
    "connection_exhaustion": {"connection_pool_low": 0.85, "traffic_spike": 0.4},
    "bad_deploy": {"version_upgrade": 0.3},
    "config_error": {},
    "db_saturation": {"traffic_spike": 0.5, "connection_pool_low": 0.3},
    "dependency_outage": {"dependency_degraded": 0.9},
    "cache_stampede": {"cache_cold": 0.8, "traffic_spike": 0.4},
}

# HIDDEN: how each true factor shifts the logit of each fix's success (SPEC §3.5 step 4).
# "no_recent_change" is an internal factor: nothing to roll back.
HIDDEN_MODIFIERS = {
    "recent_deploy": {"restart_service": -1.2, "rollback_deploy": 1.0},
    "traffic_spike": {"scale_out": 1.0, "restart_service": -0.5},
    "resource_limit_low": {"raise_resource_limits": 1.2},
    "connection_pool_low": {"raise_resource_limits": 0.8, "restart_service": 0.3},
    "cache_cold": {"clear_cache": -0.8, "scale_out": 0.5},
    "dependency_degraded": {"toggle_feature_flag": 0.8, "restart_service": -0.8},
    "feature_flag_change": {"toggle_feature_flag": 1.5},
    "disk_usage_high": {"drain_node": 0.6},
    "config_change": {"rollback_deploy": 0.5},
    "schema_migration": {"db_failover": -0.5},
    "no_recent_change": {"rollback_deploy": -3.0},
}

# Change types visible in changes_before, and the factor each implies.
CHANGE_FACTOR = {
    "deploy": "recent_deploy",
    "config_change": "config_change",
    "feature_flag": "feature_flag_change",
    "infra_change": "infra_change",
    "schema_migration": "schema_migration",
}
BENIGN_CHANGE_WEIGHTS = {"deploy": 0.55, "config_change": 0.15, "infra_change": 0.15,
                         "feature_flag": 0.10, "schema_migration": 0.05}
DB_SERVICES = {"primary-db", "billing-service", "tenant-service"}
RECENT_DEPLOY_MINUTES = 60

# The mediocre on-call runbook: first fixes people reach for, by visible signature.
RUNBOOK = {
    "mem_pressure_oom": ["restart_service", "raise_resource_limits", "scale_out"],
    "latency_degradation": ["scale_out", "restart_service", "rollback_deploy"],
    "pod_restarts": ["restart_service", "rollback_deploy", "raise_resource_limits"],
    "error_rate_5xx": ["restart_service", "rollback_deploy", "toggle_feature_flag"],
    "cpu_throttling": ["scale_out", "raise_resource_limits", "restart_service"],
    "disk_pressure": ["drain_node", "clear_cache", "restart_service"],
    "write_failures": ["restart_service", "drain_node", "scale_out"],
    "timeout_upstream": ["restart_service", "toggle_feature_flag", "scale_out"],
    "connection_resets": ["restart_service", "drain_node", "scale_out"],
    "connection_pool_exhausted": ["restart_service", "raise_resource_limits", "scale_out"],
    "timeout_upstream_db": ["restart_service", "scale_out", "db_failover"],
    "startup_failure": ["rollback_deploy", "restart_service", "toggle_feature_flag"],
    "cache_miss_storm": ["clear_cache", "scale_out", "restart_service"],
    "consumer_rebalance_storm": ["restart_service", "scale_out", "toggle_feature_flag"],
}
# Signatures where on-call almost always follows the runbook first (habit).
STRONG_RUNBOOK = {"mem_pressure_oom", "timeout_upstream"}
