"""Hindsight-backed MemoryStore (SPEC S1, S4).

The published docs (hindsight.vectorize.io) are not fully consistent about which kwargs
every client method accepts (e.g. `tags` shows up in the HTTP item schema for retain but
was missing from the summarized Python `client.recall()` signature). Per the hackathon
spec ("do not assume SDK method names or tag syntax"), this adapter does not hand-roll
HTTP calls or hard-code a kwarg list: it calls the installed `hindsight-client` package's
real methods and uses `inspect.signature` to pass only the kwargs that version actually
accepts, dropping (and logging) anything it doesn't recognize. That way it degrades
gracefully across client versions instead of crashing on an unexpected TypeError.

Every call goes through a single persistent background event loop (memory/_loop_runner.py)
via the client's *async* methods, not its sync wrappers - see that module's docstring and
docs/DECISIONS.md API6/API7 for why the sync wrappers broke under a real ASGI server.
"""

import inspect
import logging
from typing import Optional

from ._loop_runner import get_runner
from .base import MemoryStore, RecallHit, ReflectResult, RetainItem

log = logging.getLogger("memory.hindsight")

DEFAULT_CLOUD_BASE_URL = "https://api.hindsight.vectorize.io"


def _filtered_kwargs(fn, **kwargs) -> dict:
    """Keep only the kwargs `fn` actually declares (or all of them if fn takes **kwargs)."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs
    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    kept, dropped = {}, []
    for k, v in kwargs.items():
        if v is None:
            continue
        if k in params:
            kept[k] = v
        else:
            dropped.append(k)
    if dropped:
        log.warning("%s does not accept %s; dropping", getattr(fn, "__name__", fn), dropped)
    return kept


def _as_dict(resp):
    if isinstance(resp, dict):
        return resp
    return resp.model_dump() if hasattr(resp, "model_dump") else {"raw": repr(resp)}


class HindsightMemoryStore(MemoryStore):
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 300.0):
        try:
            from hindsight_client import Hindsight
        except ImportError as e:
            raise ImportError(
                "hindsight-client is not installed. Run: pip install hindsight-client -U"
            ) from e
        self.base_url = base_url or DEFAULT_CLOUD_BASE_URL
        self._runner = get_runner()
        # Constructed here, but only ever *used* (its aiohttp session created/bound) on
        # the runner's dedicated loop thread, via self._call() below - never directly.
        self._client = Hindsight(**_filtered_kwargs(
            Hindsight.__init__, base_url=self.base_url, api_key=api_key, timeout=timeout))

    def _call(self, method_name: str, **kwargs):
        """Run `self._client.a<method_name>(**filtered kwargs)` on the shared loop thread."""
        fn = getattr(self._client, f"a{method_name}")
        call_kwargs = _filtered_kwargs(fn, **kwargs)
        return self._runner.run(lambda: fn(**call_kwargs))

    # -- retain --------------------------------------------------------

    def retain_batch(self, bank_id: str, items: list[RetainItem]) -> dict:
        raw_items = [
            {k: v for k, v in {
                "content": it.content, "context": it.context, "timestamp": it.timestamp,
                "document_id": it.document_id, "tags": it.tags or None,
                "metadata": it.metadata or None,
            }.items() if v is not None}
            for it in items
        ]
        if hasattr(self._client, "aretain_batch"):
            return _as_dict(self._call("retain_batch", bank_id=bank_id, items=raw_items))
        # Fall back to one retain() call per item if this client version has no batch method.
        results = [_as_dict(self._call("retain", bank_id=bank_id, **ri)) for ri in raw_items]
        return {"success": True, "bank_id": bank_id, "items_count": len(results), "results": results}

    # -- recall ----------------------------------------------------------

    def recall(self, bank_id: str, query: str, *, tags: Optional[list[str]] = None,
              top_n: int = 30, **kwargs) -> list[RecallHit]:
        resp = self._call("recall", bank_id=bank_id, query=query, tags=tags,
                          max_tokens=kwargs.pop("max_tokens", None), budget=kwargs.pop("budget", None), **kwargs)
        results = getattr(resp, "results", None)
        if results is None and isinstance(resp, dict):
            results = resp.get("results", [])
        results = results or []

        def get(r, key, default=None):
            return getattr(r, key, r.get(key, default)) if isinstance(r, dict) else getattr(r, key, default)

        def to_raw(r):
            if isinstance(r, dict):
                return r
            if hasattr(r, "model_dump"):  # pydantic v2 models, as used by hindsight_client_api
                return r.model_dump()
            return getattr(r, "__dict__", {"repr": repr(r)})

        hits = []
        for r in results[:top_n]:
            scores = get(r, "scores", {}) or {}
            score = scores.get("final") if isinstance(scores, dict) else getattr(scores, "final", 0.0)
            hits.append(RecallHit(
                id=get(r, "id"), text=get(r, "text", ""), tags=get(r, "tags", []) or [],
                metadata=get(r, "metadata", {}) or {}, document_id=get(r, "document_id"),
                score=float(score or 0.0), raw=to_raw(r),
            ))
        return hits

    # -- reflect -----------------------------------------------------------

    def reflect(self, bank_id: str, query: str, **kwargs) -> ReflectResult:
        resp = self._call("reflect", bank_id=bank_id, query=query, **kwargs)
        text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else str(resp))
        raw = resp if isinstance(resp, dict) else (resp.model_dump() if hasattr(resp, "model_dump") else None)
        return ReflectResult(text=text, raw=raw)

    # -- reset (SPEC S10.7) --------------------------------------------------

    def reset(self, bank_id: str) -> None:
        for method_name in ("clear_memories", "delete_bank"):
            if not hasattr(self._client, f"a{method_name}"):
                continue
            try:
                self._call(method_name, bank_id=bank_id)
                log.info("Reset bank %s via %s", bank_id, method_name)
                return
            except Exception as e:  # noqa: BLE001 - try the next strategy
                log.warning("%s failed for bank %s: %s", method_name, bank_id, e)
        raise RuntimeError(
            f"No supported reset method found on installed hindsight-client for bank {bank_id!r} "
            "(tried clear_memories, delete_bank)."
        )
