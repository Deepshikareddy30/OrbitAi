"""Rebuild the demo memory from the training snapshot (SPEC S10.7).

Reloads data/incidents.json fresh, wipes and re-retains the configured MemoryStore's
bank, clears saved weight versions and the audit log, then fits a fresh v1. Equivalent
to POST /api/demo/reset, but usable without the API server running (e.g. right before a
demo, or after regenerating the dataset with `python -m generator`).

Usage: python -m scripts.reset_demo [--memory fake|hindsight]
"""

import argparse

from api.state import build_default_state


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--memory", choices=["fake", "hindsight"], default=None,
                    help="Overrides MEMORY_STORE env var")
    args = ap.parse_args()

    # build_default_state() already does a full retain-from-snapshot on construction,
    # so simply (re)building it accomplishes the reset - no separate AppState needed.
    state = build_default_state(memory_kind=args.memory)
    print(f"Bank {state.bank_id!r} reset: {len(state.incidents)} incidents reloaded, "
         f"weights at {state.current_weights().version}, store={type(state.store).__name__}")


if __name__ == "__main__":
    main()
