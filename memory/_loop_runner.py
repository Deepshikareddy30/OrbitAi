"""A single persistent background event loop, shared by every HindsightMemoryStore call.

Why this exists (docs/DECISIONS.md API6/API7): hindsight-client's *sync* wrapper methods
(`retain_batch`, `recall`, `reflect`, ...) each do their own `loop.run_until_complete(...)`
internally. That breaks two different ways once a real ASGI server is involved:

1. Called from a thread that already has a *running* loop (e.g. eager app construction
   at module-import time under `uvicorn module:app`) -> "This event loop is already
   running".
2. Called from FastAPI's per-request thread pool, where each call may land on a
   *different* worker thread: hindsight-client's underlying aiohttp session gets bound
   to whichever loop was active the first time it was used, then breaks on the next
   call from a different thread/loop with "Timeout context manager should be used
   inside a task" (aiohttp session reused across event loops).

The fix is the standard pattern for driving an asyncio-native client from sync,
multi-threaded callers: run ONE event loop forever in ONE dedicated background thread,
and marshal every call onto it via `run_coroutine_threadsafe`. The Hindsight client (and
its aiohttp session) is then always used from the exact same loop it was created in,
no matter which caller thread requests it.
"""

import asyncio
import threading
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class LoopRunner:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="hindsight-loop")
        self._thread.start()

    def run(self, coro_factory: Callable[[], Awaitable[T]], timeout: float = 120.0) -> T:
        """`coro_factory` (not the coroutine itself) so it's only ever created on the
        runner's own loop/thread - creating a coroutine object is fine anywhere, but
        this keeps the pattern safe if that ever stops being true."""
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        return future.result(timeout=timeout)


_runner: LoopRunner | None = None


def get_runner() -> LoopRunner:
    global _runner
    if _runner is None:
        _runner = LoopRunner()
    return _runner
