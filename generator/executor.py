"""Simulated fix execution (SPEC S7 steps 1-2): 'Approved fix is executed against the
simulated environment. An outcome check watches simulated metrics ... and returns
resolved/failed/recurred and time_to_recover_min.'

This is the only place besides validate.py/eval allowed to consult hidden ground truth
to decide whether a fix actually worked. Everything downstream (feedback/, engine/,
memory/, api/, ui/) only ever sees the returned attempt dict, never the root cause or
p_success behind it - see tests/test_hidden_leak.py.
"""

from .simulate import fix_breakdown, simulate_attempt_outcome


def execute_fix(true_root_cause: str, true_factors, changes_before: list[dict], fix: str,
                cfg: dict, rng, *, human_override: bool = False, override_reason: str = None):
    """Run `fix` against an incident with the given (hidden) true root cause and factors.
    Returns (attempt, hidden_debug) exactly like generator.simulate.run_attempts's items -
    `attempt` carries no hidden fields.
    """
    breakdown = fix_breakdown(true_root_cause, set(true_factors), changes_before)
    return simulate_attempt_outcome(fix, breakdown, cfg, rng, override=human_override,
                                    override_reason=override_reason)
