"""Request bodies. Responses are plain dicts (dataclasses.asdict) - no hidden fields
ever appear in them, since everything here operates on engine/memory/simworld outputs."""

from typing import Optional

from pydantic import BaseModel


class ExecuteFixRequest(BaseModel):
    fix: str
    writer: str = "on-call-engineer"
    authorized: bool = True
    human_override: bool = False
    override_reason: Optional[str] = None


class PoisonRequest(BaseModel):
    """For the poisoning-guard demo (SPEC S7): inject a fabricated claim directly,
    bypassing the simulator, to show it gets stored-but-blocked."""
    fix: str
    outcome: str = "resolved"
    writer: str = "anonymous-script"
    authorized: bool = False
    verified: bool = False


class CourtroomRequest(BaseModel):
    fix: Optional[str] = None  # defaults to the top-ranked (verdict-priority) recommendation
    force: bool = False        # bypass the should_convene() risk/verdict/trust trigger


class AgentActionRequest(BaseModel):
    """Resumes the paused agent graph (agent/graph.py) at its human-in-the-loop
    interrupt. `decision` is 'approve' or 'reject' - anything else leaves the graph
    paused (SPEC's 'investigate further' is a frontend-only affordance: expand the
    already-shown evidence, no backend call)."""
    decision: str
    fix: Optional[str] = None  # override the recommended fix, if the human picks a different one
    writer: str = "on-call-engineer"
    authorized: bool = True
    reason: Optional[str] = None
