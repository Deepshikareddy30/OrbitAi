"""Structural checks on the generated dataset (milestone 1 validation).

Reads hidden truth, so it lives in the generator package.
"""

from collections import Counter

from . import world as W


def _recent_deploy(inc):
    return any(c["type"] == "deploy" and c["minutes_before"] <= W.RECENT_DEPLOY_MINUTES
               for c in inc["changes_before"])


def _attempt_outcomes(inc, fix):
    return [a for a in inc["attempts"] if a["fix"] == fix and a["verified"]]


def lookalike_counts(incidents, root_causes, split="train"):
    """Counts backing demo C (SPEC §3.5 'Required look-alike structure')."""
    leak_restart_pass = deploy_restart_fail = 0
    for inc in incidents:
        if inc["split"] != split or inc["error_signature"] != "mem_pressure_oom":
            continue
        rc = root_causes[inc["id"]]["root_cause"]
        outs = [a["outcome"] for a in _attempt_outcomes(inc, "restart_service")]
        if not _recent_deploy(inc) and "resolved" in outs:
            leak_restart_pass += 1
        if _recent_deploy(inc) and rc == "bad_deploy" and any(o in ("failed", "recurred") for o in outs):
            deploy_restart_fail += 1
    return {"leak_like_restart_resolved": leak_restart_pass,
            "deploy_then_restart_failed": deploy_restart_fail}


def summary(incidents, root_causes, cfg):
    train = [i for i in incidents if i["split"] == "train"]
    attempts = [a for i in incidents for a in i["attempts"]]
    withheld = (cfg["withheld_combo"]["service"], cfg["withheld_combo"]["root_cause"])
    return {
        "incidents": len(incidents),
        "split": dict(Counter(i["split"] for i in incidents)),
        "attempts": len(attempts),
        "train_attempts": sum(len(i["attempts"]) for i in train),
        "outcomes": dict(Counter(a["outcome"] for a in attempts)),
        "unverified_attempts": sum(not a["verified"] for a in attempts),
        "self_healed_attempts": sum(h["self_healed"] for r in root_causes.values() for h in r["attempts"]),
        "train_attempts_per_fix": dict(Counter(a["fix"] for i in train for a in i["attempts"])),
        "root_causes": dict(Counter(r["root_cause"] for r in root_causes.values())),
        "services": dict(Counter(i["service"] for i in incidents)),
        "lookalike_train": lookalike_counts(incidents, root_causes),
        "withheld_combo_present": sum((i["service"], root_causes[i["id"]]["root_cause"]) == withheld
                                      for i in incidents),
        "novel_signature_present": sum(i["error_signature"] == W.NOVEL_SIGNATURE for i in incidents),
    }
