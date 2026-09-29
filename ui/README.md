# OrbitAI UI

React + Vite + Tailwind frontend for OrbitAI, the incident trust engine. See the
[root README](../README.md) for what this project is and where Hindsight is used, and
[docs/SPEC.md](../docs/SPEC.md) §2 for the UI's role.

## Setup

```bash
npm install
npm run dev
```

Proxies `/api` to `http://127.0.0.1:8000` in dev (see `vite.config.js`), so run the
FastAPI backend (`python -m uvicorn api.app:app --reload --port 8000` from the repo
root) alongside it.

For a production build against a deployed backend, set `VITE_API_BASE` (see
`.env.example`) to the backend's `/api` URL before `npm run build`.

## Pages

| Route | What it shows |
|---|---|
| `/` | Incident timeline: list, filterable by train/held-out |
| `/incidents/:id` | The core view — alert, recalled cases, Trust Ledger (ranked fixes, two-sided evidence), Adaptive Gate decision, execute-a-fix |
| `/demo` | The 5-scenario demo upload walkthrough (SPEC §8) + the poisoning-guard demo |
| `/gate` | Adaptive Gate rule reference (real logic, evaluated per-recommendation on the incident page) |
| `/health` | AI Health — baseline vs. OrbitAI charts from `eval/results.json`, incident-level comparison |
| `/audit` | Audit Log — every retain/refit/gate/override/blocked-write event |

## Stack

React 19, React Router 7, Tailwind CSS v4 (CSS-first config, see `src/index.css`),
Recharts for AI Health's charts.
