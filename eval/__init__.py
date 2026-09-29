"""Held-out replay evaluation (SPEC S10). Allowed to read hidden/ - it's the evaluator,
alongside generator/ and simworld/. engine/memory/api/ui/feedback must never import
anything from this package or from hidden/ directly - see tests/test_hidden_leak.py.
"""
