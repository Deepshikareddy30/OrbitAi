"""REST API wrapping memory/engine/gate/feedback. Never reads the ground-truth folder
that only the generator and evaluator (and its own simworld boundary) may touch - see
tests/test_hidden_leak.py.
"""
