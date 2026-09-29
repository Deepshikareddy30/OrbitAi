"""In-process fake MemoryStore for unit tests (and local/demo dev without a Hindsight
key) - SPEC S1 explicitly allows this as a test-only fake.

Not a substitute for the real Hindsight integration test - it approximates keyword
retrieval with IDF-weighted token overlap, nothing like Hindsight's actual semantic/
keyword/graph fusion. IDF weighting (docs/DECISIONS.md MEM6) matters here: without it,
generic words shared by every incident ("incident", "tried", "min") drown out the
distinctive ones (service names, error signatures) that should actually drive matches.
"""

import math
import re
from collections import defaultdict
from typing import Optional

from .base import MemoryStore, RecallHit, ReflectResult, RetainItem

_WORD = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class InMemoryStore(MemoryStore):
    def __init__(self):
        self._banks: dict[str, list[RetainItem]] = defaultdict(list)

    def retain_batch(self, bank_id: str, items: list[RetainItem]) -> dict:
        self._banks[bank_id].extend(items)
        return {"success": True, "bank_id": bank_id, "items_count": len(items), "async": False}

    def recall(self, bank_id: str, query: str, *, tags: Optional[list[str]] = None,
              top_n: int = 30, **kwargs) -> list[RecallHit]:
        items = self._banks.get(bank_id, [])
        if tags:
            items = [it for it in items if set(tags) & set(it.tags)]
        q = _tokens(query)
        if not q or not items:
            return []

        item_tokens = [_tokens(it.content) for it in items]
        df = defaultdict(int)
        for toks in item_tokens:
            for t in q & toks:
                df[t] += 1
        n = len(items)
        # Smoothed IDF: always positive, and query terms nobody shares still contribute
        # (they just can't match anything, so they never affect a real score).
        idf = {t: math.log((n + 1) / (df[t] + 1)) + 1.0 for t in q}
        max_score = sum(idf.values()) or 1.0

        hits = []
        for i, (item, toks) in enumerate(zip(items, item_tokens)):
            overlap = q & toks
            if not overlap:
                continue
            score = sum(idf[t] for t in overlap) / max_score
            hits.append(RecallHit(id=item.document_id or str(i), text=item.content, tags=item.tags,
                                  metadata=item.metadata, document_id=item.document_id, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_n]

    def reflect(self, bank_id: str, query: str, **kwargs) -> ReflectResult:
        hits = self.recall(bank_id, query, top_n=5)
        text = f"{len(hits)} related memories found." if hits else "No related memories found."
        return ReflectResult(text=text, raw={"hit_count": len(hits)})

    def reset(self, bank_id: str) -> None:
        self._banks[bank_id] = []
