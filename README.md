# OrbitAI — Incident Trust Engine



An incident-response agent that recalls similar past incidents from **Hindsight** memory,
scores its recommended fix with a Bayesian-smoothed trust score computed in plain code
(never by an LLM), shows two-sided evidence (cases that passed vs. cases that failed),
routes approval through a risk-tiered Adaptive Gate, and re-learns its feature weights
every time a verified outcome comes back.

Full design spec: [`docs/SPEC.md`](docs/SPEC.md). Running decision log: [`docs/DECISIONS.md`](docs/DECISIONS.md).

**Everything here is simulated.** There is no real production traffic, no real
Slack/PagerDuty/Datadog integration. A generator (`generator/`) builds a synthetic
6-month incident history for a fictional 10-service SaaS platform, with a hidden
ground-truth simulator deciding whether each attempted fix actually worked. The claim
this project makes is that the mechanism — similarity-weighted trust scoring, two-sided
evidence, adaptive gating, continual re-learning — recovers real structure from noisy
outcomes and improves decisions on unseen incidents. It is not a claim proven on real
production data. See `docs/SPEC.md` §11 for the full honesty notes.

## Where Hindsight is used

Hindsight is the memory system, not a bolt-on. It is used for exactly three operations,
wrapped behind `memory/base.py`'s `MemoryStore` interface so the rest of the codebase
never depends on the SDK directly:

| Operation | Where | What |
|---|---|---|
| **retain** | `memory/loader.py`, `feedback/loop.py` | Every verified attempt is retained as narrative text plus tags (`incident_id`, `service`, `env`, `fix`, `outcome`, `verified`, one tag per contributing factor) — see `memory/text.py`. One memory per attempt, not per incident. |
| **recall** | `engine/recall_bridge.py` | A new incident's service/signature/symptoms/changes are turned into a natural-language query (`memory/text.py::build_recall_query`); Hindsight returns candidate memories, deduplicated back to structured incident records by `incident_id`. |
| **reflect** | `feedback/loop.py` | Called after every accepted (verified + authorized) outcome, to produce a readable observation shown in the Trust Ledger. Reflect text is **never** used in the math — it's narration only. |

The **engine** (`engine/`) is what sits on top: it keeps the structured feature vectors
and learned weights (derived state — JSON files, never re-derivable from Hindsight
alone), computes similarity, builds the two-sided evidence table, and produces the trust
score. This division of labor is deliberate — see `docs/SPEC.md` §2.

We built `memory/hindsight_store.py` against the real installed `hindsight-client`
package (inspecting its actual method signatures via `inspect.signature`, not guessing
from docs — see `docs/DECISIONS.md` MEM1/MEM2), and verified it end to end against real
Hindsight Cloud (`tests/test_hindsight_store.py`, plus a live server hitting every route
— retain, recall, reflect, reset — see `docs/DECISIONS.md` API7 for two real
event-loop/threading bugs that only showed up running the actual server, not in tests).
The app defaults to `memory/fake_store.py`, an in-memory keyword-overlap stand-in
explicitly allowed for tests (`MemoryStore` is an interface; this is one implementation
of it), unless `.env` sets `MEMORY_STORE=hindsight` plus `HINDSIGHT_API_KEY` — `.env` is
loaded automatically on startup (`api/app.py`), no manual `export` needed.

## Architecture

```
generator/    offline dataset + hidden ground truth (only this, simworld/, eval/ may read hidden/)
memory/       MemoryStore interface + Hindsight adapter + in-memory fake
engine/       features, per-fix logistic regression (reflection), similarity, evidence,
              trust score, ranking, Adaptive Gate
feedback/     the verified-outcome loop: retain, refit, poisoning guard
simworld/     the only boundary that looks up hidden truth to simulate an outcome
api/          FastAPI layer over all of the above
eval/         held-out replay: baseline (no memory) vs OrbitAI, results.json, charts
ui/           React frontend
```

See `tests/test_hidden_leak.py` — an AST-based check that fails the build if `engine/`,
`memory/`, `api/`, `ui/` or `feedback/` ever reference the ground-truth folder.

## Running it

### Backend

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in HINDSIGHT_API_KEY / GROQ_API_KEY / OPENROUTER_* if you have them
python -m generator     # generates data/ and hidden/
python -m pytest -q     # 116 passing if .env has a real HINDSIGHT_API_KEY, else 115 + 1 skipped
python -m uvicorn api.app:app --reload --port 8000
```

`.env` is loaded automatically on startup. Defaults to the in-memory fake store
(`MEMORY_STORE=fake` or unset) so it boots without credentials; set
`MEMORY_STORE=hindsight` in `.env` once `HINDSIGHT_API_KEY` is filled in. First boot
against real Hindsight takes 30-60s (retaining ~400 attempt-memories for real, not
instant like the fake).

### Frontend

```bash
cd ui
npm install
npm run dev   # proxies /api to http://127.0.0.1:8000 (see vite.config.js)
```

### Evaluation (the held-out numbers)

```bash
python -m eval.run             # ~60-90s, writes eval/results.json
python -m eval.export_charts   # writes PNGs to eval/charts/ for slides
```

Served to the frontend's AI Health page via `GET /api/eval/results`. Falls back to a
small deterministic heuristic (clearly labeled `used_llm: false`) for the no-memory
baseline when `GROQ_API_KEY` isn't set — see `docs/DECISIONS.md` EVAL1.

### Deployment

Backend on Render, frontend on Vercel (both free tier, both from GitHub) — see
`docs/SPEC.md` §2.1. Render's free tier sleeps when idle; warm it up before a demo.

## What the numbers actually say

Current replay (fake store, heuristic baseline, 60 held-out incidents —
`docs/DECISIONS.md` EVAL3/MEM6/API5): OrbitAI beats a domain-aware heuristic baseline
overall (best-fix rate 0.633 vs 0.567, mean regret 0.196 vs 0.265), and **wins decisively
on the deliberately ambiguous look-alike subset** (100% vs 77%, correctly flagging
`conflict` 85% of the time) — exactly the class of case surface-level pattern matching
can't disambiguate, which is the actual pitch. Weight-recovery correlation against the
hidden simulator's true modifiers: 0.86.

Earlier in this same session, the *first* version of this replay had OrbitAI roughly
at parity with the baseline (or worse) — not because the trust math was wrong, but
because the in-memory fake store's recall stage (a keyword-overlap stand-in for real
Hindsight, used only because we don't have a Hindsight Cloud key yet) was quietly
bottlenecking which candidates it ever saw. Fixing that retrieval gap (not the scoring
logic) is what moved these numbers — left in as evidence the honesty principle throughout
this build (SPEC §10.7, §11) is actually being followed, not just stated.
