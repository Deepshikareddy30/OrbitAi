"""FastAPI app factory. `uvicorn api.app:app` runs the real thing (Hindsight if
MEMORY_STORE=hindsight is set, else the in-memory fake so it boots without credentials).

Loads .env automatically (repo root) so `MEMORY_STORE`/`HINDSIGHT_API_KEY`/etc. don't
have to be exported by hand every time the server starts - see docs/DECISIONS.md API6.

Safe to build state (including real Hindsight calls) directly at module-import time even
though `uvicorn module:app` imports this from inside its own already-running event loop:
HindsightMemoryStore marshals every call onto its own persistent background loop
(memory/_loop_runner.py), so it never touches whatever loop the calling thread has.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.graph import build_graph

from .agent_routes import router as agent_router
from .routes import router
from .state import AppState, build_default_state

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def create_app(state: AppState | None = None) -> FastAPI:
    app = FastAPI(title="OrbitAI API", description="Incident Trust Engine (SPEC.md)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
        allow_methods=["*"], allow_headers=["*"],
    )
    app.state.trustlens = state or build_default_state()
    app.state.agent_graph = build_graph(app.state.trustlens)
    app.include_router(router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    return app


app = create_app()
