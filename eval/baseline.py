"""The no-memory baseline (SPEC S10.1): 'the same base LLM used everywhere else in the
project, with no memory'. Input: service, environment, symptoms, changes_before,
slack_thread, plus the fix catalog. Output: a ranked list of fixes from the catalog.

Falls back to a small, clearly-labeled heuristic (not the LLM) when GROQ_API_KEY isn't
set, so `python -m eval.run` still produces real, honestly-labeled numbers without
credentials - see docs/DECISIONS.md EVAL1. Every cached/returned result carries
`used_llm: bool` so results.json never silently claims LLM numbers it doesn't have.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("eval.baseline")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"


def _present_incident_text(incident: dict, fixes_catalog: list[dict]) -> str:
    s = incident["symptoms"]
    changes = "; ".join(f"{c['type']} {c['detail']} ({c['minutes_before']}m before)"
                        for c in incident["changes_before"]) or "none"
    fixes = ", ".join(f["fix"] for f in fixes_catalog)
    slack = " | ".join(incident["slack_thread"][:4])
    return (
        f"Service: {incident['service']}\nEnvironment: {incident['environment']}\n"
        f"Error signature: {incident['error_signature']}\n"
        f"Symptoms: p99={s['p99_ms']}ms error_rate={s['error_rate']:.1%} cpu={s['cpu']:.0%} mem={s['mem']:.0%}\n"
        f"Changes before the incident: {changes}\nSlack: {slack}\n"
        f"Available fixes: {fixes}\n\n"
        "Rank ALL of the available fixes from most to least likely to resolve this incident. "
        "Respond with ONLY a JSON array of fix names, most likely first, e.g. "
        '["restart_service", "scale_out", ...]. No other text.'
    )


def _parse_ranked_fixes(text: str, valid_fixes: list[str]) -> list[str]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in LLM response: {text!r}")
    ranked = [f for f in json.loads(match.group(0)) if f in valid_fixes]
    ranked += [f for f in valid_fixes if f not in ranked]  # ensure every fix is ranked
    return ranked


def call_groq_baseline(incident: dict, fixes_catalog: list[dict], api_key: str,
                       timeout: float = 20.0) -> list[str]:
    """Raises on any failure (timeout, bad response, function-calling error) - callers
    should catch and fall back (SPEC S5.5: 'Handle function-calling errors gracefully')."""
    valid_fixes = [f["fix"] for f in fixes_catalog]
    body = {
        "model": GROQ_MODEL, "temperature": 0,
        "messages": [
            {"role": "system", "content": "You are an SRE assistant ranking possible fixes for a "
                                          "production incident. You have no memory of past incidents."},
            {"role": "user", "content": _present_incident_text(incident, fixes_catalog)},
        ],
    }
    resp = httpx.post(GROQ_URL, json=body, timeout=timeout,
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _parse_ranked_fixes(text, valid_fixes)


# -- context-blind fallback (used only when GROQ_API_KEY is unset or the call fails) --

_KEYWORD_GUESS = [
    (re.compile(r"oom|mem_pressure|memory"), "restart_service"),
    (re.compile(r"cpu|throttl"), "scale_out"),
    (re.compile(r"disk"), "drain_node"),
    (re.compile(r"cache"), "clear_cache"),
    (re.compile(r"5xx|startup_failure|error_rate"), "toggle_feature_flag"),
    (re.compile(r"connection_pool|pool_exhaust"), "raise_resource_limits"),
    (re.compile(r"db|upstream_db"), "db_failover"),
]


def heuristic_fallback_baseline(incident: dict, fixes_catalog: list[dict]) -> list[str]:
    """A small, deterministic, context-blind (no history) guess from the error signature
    and whether a change preceded the incident - approximates what a memory-free LLM
    guess would look like, without a network call. NOT the real LLM baseline."""
    valid_fixes = [f["fix"] for f in fixes_catalog]
    guess = []
    if incident["changes_before"]:
        guess.append("rollback_deploy")
    sig = incident["error_signature"]
    for pattern, fix in _KEYWORD_GUESS:
        if pattern.search(sig) and fix not in guess:
            guess.append(fix)
    guess.append("restart_service")  # generic first response
    guess += [f for f in valid_fixes if f not in guess]
    return [f for f in guess if f in valid_fixes]


# -- cached, incident-keyed baseline lookup ------------------------------------

def load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}


def save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def get_baseline(incident: dict, fixes_catalog: list[dict], cache: dict,
                 api_key: Optional[str] = None) -> dict:
    """Returns {'ranked': [...], 'used_llm': bool}. Cached in `cache` by incident id -
    callers persist `cache` to eval/baseline_cache.json (SPEC S10.1)."""
    if incident["id"] in cache:
        return cache[incident["id"]]

    api_key = api_key or os.environ.get("GROQ_API_KEY")
    used_llm = False
    if api_key:
        try:
            ranked = call_groq_baseline(incident, fixes_catalog, api_key)
            used_llm = True
        except Exception as e:  # noqa: BLE001 - fall back on any LLM/network failure
            log.warning("Groq baseline call failed for %s: %s; using heuristic fallback",
                       incident["id"], e)
            ranked = heuristic_fallback_baseline(incident, fixes_catalog)
    else:
        ranked = heuristic_fallback_baseline(incident, fixes_catalog)

    entry = {"ranked": ranked, "used_llm": used_llm}
    cache[incident["id"]] = entry
    return entry
