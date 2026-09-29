"""MemoryStore factory. engine/, api/, ui/ should import get_store(), never a concrete
provider class, so the interface (SPEC S1) stays the only contract they depend on.
"""

import os

from .base import MemoryStore, RecallHit, ReflectResult, RetainItem

DEFAULT_BANK_ID = "trustlens-incidents"


def get_store(kind: str | None = None) -> MemoryStore:
    """kind: 'hindsight' (default if HINDSIGHT_API_KEY is set) or 'fake' (tests)."""
    kind = kind or os.environ.get("MEMORY_STORE", "hindsight")
    if kind == "fake":
        from .fake_store import InMemoryStore
        return InMemoryStore()
    if kind == "hindsight":
        from .hindsight_store import HindsightMemoryStore
        return HindsightMemoryStore(
            base_url=os.environ.get("HINDSIGHT_BASE_URL"),
            api_key=os.environ.get("HINDSIGHT_API_KEY"),
        )
    raise ValueError(f"Unknown memory store kind: {kind!r}")


__all__ = ["MemoryStore", "RecallHit", "ReflectResult", "RetainItem", "get_store", "DEFAULT_BANK_ID"]
