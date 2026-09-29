"""Feedback loop (SPEC S7): retain verified outcomes, refit weights, guard against
memory poisoning. Never reads the ground-truth folder that only the generator and
evaluator may touch - see tests/test_hidden_leak.py. Outcomes arrive pre-computed
(e.g. from generator.executor, or a real human filing a report) as plain attempt dicts.
"""
