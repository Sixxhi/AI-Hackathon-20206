"""ImmuneMemory — the memory layer (P2).

In-memory for v1. Swap the retrieval internals for Redis vector search later;
the public surface (add/search/quarantine/parole/snapshot) stays identical.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .schemas import MemoryRecord


class ImmuneMemory:
    def __init__(self, threshold: float = 0.3, gate: bool = True):
        self.threshold = threshold
        self.gate = gate                       # False -> naive store (no immune filtering)
        self._mems: dict[str, MemoryRecord] = {}

    # --- write ---------------------------------------------------------------
    def add(self, mem: MemoryRecord) -> MemoryRecord:
        self._mems[mem.id] = mem
        return mem

    def get(self, mem_id: str) -> Optional[MemoryRecord]:
        return self._mems.get(mem_id)

    def all(self) -> list[MemoryRecord]:
        return list(self._mems.values())

    # --- read ----------------------------------------------------------------
    def _candidates(self, topic: str, exclude: Iterable[str] = ()) -> list[MemoryRecord]:
        """Retrieve memories matching a topic. Swap this body for vector search."""
        exclude = set(exclude)
        hits = [m for m in self._mems.values() if m.topic == topic and m.id not in exclude]
        # newest first => models recency bias that lets fresh poison win
        return sorted(hits, key=lambda m: m.seq, reverse=True)

    def search(self, topic: str, exclude: Iterable[str] = ()) -> list[MemoryRecord]:
        cands = self._candidates(topic, exclude)
        if not self.gate:
            return cands
        return [m for m in cands if m.is_admissible(self.threshold)]

    # --- immune controls -----------------------------------------------------
    def decay(self, mem_id: str, alpha: float = 0.5, target: float = 0.0) -> None:
        m = self._mems[mem_id]
        m.trust = m.trust + alpha * (target - m.trust)
        if m.trust < self.threshold:
            m.status = "quarantined"

    def quarantine(self, mem_id: str) -> None:
        m = self._mems[mem_id]
        m.status = "quarantined"
        m.trust = min(m.trust, self.threshold - 0.01)

    def parole(self, mem_id: str) -> None:
        m = self._mems[mem_id]
        m.status = "active"
        m.trust = self.threshold + 0.1

    def quarantined(self) -> list[MemoryRecord]:
        return [m for m in self._mems.values() if m.status == "quarantined"]

    # --- viz -----------------------------------------------------------------
    def snapshot(self) -> list[dict]:
        return [
            {"id": m.id, "text": m.text, "source": m.source,
             "trust": round(m.trust, 3), "status": m.status}
            for m in sorted(self._mems.values(), key=lambda m: m.seq)
        ]
