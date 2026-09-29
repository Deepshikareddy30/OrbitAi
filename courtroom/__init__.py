"""Courtroom: Advocate + Challenger independently argue over the SAME already-computed
evidence (SPEC principle carried over from S5.5: an LLM may narrate, it never decides a
number). The trust adjustment and every label in the Courtroom Assessment are computed
in plain code from the real FixEvidence - see debate.py::assess(). The two LLM calls
only produce the human-readable argument text.

Never reads the ground-truth folder - see tests/test_hidden_leak.py.
"""
