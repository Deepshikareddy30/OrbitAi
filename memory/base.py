"""MemoryStore interface (SPEC S1, S4). The rest of the codebase depends only on this;
Hindsight-specific details live behind hindsight_store.py.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RetainItem:
    """One narrative memory to store. Mirrors Hindsight's retain item shape
    (content/context/timestamp/document_id/tags/metadata) - see docs/DECISIONS.md MEM2.
    """
    content: str
    context: Optional[str] = None
    timestamp: Optional[str] = None       # ISO 8601
    document_id: Optional[str] = None     # used for idempotent upsert (e.g. "INC-0042#restart_service")
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class RecallHit:
    id: Optional[str]
    text: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    document_id: Optional[str] = None
    score: float = 0.0
    raw: Optional[dict] = None  # untouched provider payload, for debugging / the Memory Inspector UI


@dataclass
class ReflectResult:
    text: str
    raw: Optional[dict] = None


class MemoryStore(ABC):
    """retain / recall / reflect, and a reset hook for the demo (SPEC S10.7)."""

    @abstractmethod
    def retain_batch(self, bank_id: str, items: list[RetainItem]) -> dict:
        ...

    def retain(self, bank_id: str, item: RetainItem) -> dict:
        return self.retain_batch(bank_id, [item])

    @abstractmethod
    def recall(self, bank_id: str, query: str, *, tags: Optional[list[str]] = None,
              top_n: int = 30, **kwargs) -> list[RecallHit]:
        ...

    @abstractmethod
    def reflect(self, bank_id: str, query: str, **kwargs) -> ReflectResult:
        ...

    @abstractmethod
    def reset(self, bank_id: str) -> None:
        """Wipe a bank's memories for the demo reset flow. Recreate-empty semantics."""
        ...
