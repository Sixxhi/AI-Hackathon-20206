"""ImmuneMemory — the memory layer (P2).

Source of truth is in-memory (deterministic — the shadow-replay moat reads from
here, so attribution never depends on a network service). When the matching env
vars are set, two integrations attach as SIDE EFFECTS, never in the read path:

  - Redis  (USE_REDIS):  every mutation is mirrored to Redis hashes — persistence
                         across runs + the substrate for vector search later.
                         Memories map 1:1 onto `immune:<ns>:mem:<id>` hashes.
  - Sentry (USE_SENTRY): quarantine() fires an alert event — "the agent caught
                         itself poisoning its own memory."

Both are wrapped so a service outage degrades to the pure in-memory path; the
offline demo and the invariant tests run identically with the flags off.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import config
from .provenance import ProvenanceGraph
from .schemas import MemoryRecord


class ImmuneMemory:
    def __init__(self, threshold: float = 0.3, gate: bool = True):
        self.threshold = threshold
        self.gate = gate                       # False -> naive store (no immune filtering)
        self._mems: dict[str, MemoryRecord] = {}
        self._ns = "immune" if gate else "naive"
        self.provenance = ProvenanceGraph()    # derivation lineage (chain of custody)
        self._redis = _redis_client()          # None unless USE_REDIS + reachable
        self._index_ready = False              # RediSearch vector index created lazily
        _sentry_init()                         # no-op unless USE_SENTRY

    # --- write ---------------------------------------------------------------
    def add(self, mem: MemoryRecord, parents: Iterable[str] = ()) -> MemoryRecord:
        """Store a memory. `parents` records the memories it was DERIVED from, so
        a later verdict can cascade-quarantine everything distilled from poison."""
        self._mems[mem.id] = mem
        self.provenance.add(mem.id, parents)
        self._mirror(mem)
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
        self._mirror(m)

    def quarantine(self, mem_id: str) -> None:
        m = self._mems[mem_id]
        m.status = "quarantined"
        m.trust = min(m.trust, self.threshold - 0.01)
        self._mirror(m)
        # Sentry reporting moved to immune/sentry_report.py — fired once per
        # attribution (with full root-cause context) from replay/mcp, not once
        # per memory here, so cascades don't spam duplicate issues.

    def quarantine_cascade(self, mem_id: str) -> list[str]:
        """Quarantine a culprit AND every memory derived from it (the contamination
        subtree). Returns all ids quarantined. A rule distilled from poison is
        poison even when it reads clean — see provenance.py / MemLineage."""
        targets = self.provenance.contaminated([mem_id])
        out = []
        for mid in targets:
            if mid in self._mems and self._mems[mid].status != "quarantined":
                self.quarantine(mid)
                out.append(mid)
        return sorted(out)

    def parole(self, mem_id: str) -> None:
        m = self._mems[mem_id]
        m.status = "active"
        m.trust = self.threshold + 0.1
        self._mirror(m)

    def quarantined(self) -> list[MemoryRecord]:
        return [m for m in self._mems.values() if m.status == "quarantined"]

    # --- viz -----------------------------------------------------------------
    def snapshot(self) -> list[dict]:
        return [
            {"id": m.id, "text": m.text, "source": m.source,
             "trust": round(m.trust, 3), "status": m.status}
            for m in sorted(self._mems.values(), key=lambda m: m.seq)
        ]

    # --- Redis vector search (recall path; the moat still reads in-memory) ----
    def _mirror(self, m: MemoryRecord) -> None:
        if self._redis is None:
            return
        try:
            from . import embed, redis_index
            if not self._index_ready:
                redis_index.ensure_index(self._redis, self._ns, dim=len(embed.embed("x")))
                self._index_ready = True
            self._redis.hset(f"immune:{self._ns}:mem:{m.id}", mapping={
                "id": m.id, "topic": m.topic or "", "text": m.text,
                "answer": getattr(m, "answer", "") or "",
                "source": m.source, "trust": f"{m.trust:.4f}", "status": m.status,
                "seq": str(m.seq),
                "embedding": redis_index.vec_bytes(embed.embed(m.text)),
            })
            self._redis.sadd(f"immune:{self._ns}:ids", m.id)
        except Exception:
            self._redis = None                 # degrade silently; demo must never break

    @property
    def vector_backend(self) -> str:
        """Where recall runs: real Redis vector search, or the in-memory fallback."""
        return "Redis vector search (RediSearch KNN)" if self._redis is not None else "in-memory cosine"

    def vector_candidates(self, query: str, k: int = 50):
        """Recall via real RediSearch KNN. Returns [(similarity, MemoryRecord)] or
        None when Redis is unavailable (caller then falls back to in-memory cosine).
        Quarantined memories are excluded by the index query itself."""
        if self._redis is None:
            return None
        try:
            from . import embed, redis_index
            qv = embed.embed(query)
            hits = redis_index.knn(self._redis, self._ns, qv, k)
            return [(sim, self._mems[mid]) for mid, sim in hits if mid in self._mems]
        except Exception:
            return None


def _redis_client():
    if not config.USE_REDIS:
        return None
    try:
        import redis
        # RESP2 + binary: vector search needs raw float32 blobs (decode_responses
        # would corrupt them) and the classic list reply format for FT.SEARCH. We
        # never read text values back from Redis — the in-memory store is the
        # source of truth — so binary mode costs nothing.
        client = redis.from_url(config.REDIS_URL, protocol=2)
        client.ping()
        return client
    except Exception:
        return None


_sentry_ready = False


def _sentry_init() -> None:
    global _sentry_ready
    if _sentry_ready or not config.USE_SENTRY:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=config.SENTRY_DSN, traces_sample_rate=0.0)
        _sentry_ready = True
    except Exception:
        pass


def _sentry_quarantine(m: MemoryRecord) -> None:
    if not (_sentry_ready and config.USE_SENTRY):
        return
    try:
        import sentry_sdk
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("immune.event", "quarantine")
            scope.set_tag("immune.source", m.source)
            scope.set_context("memory", {
                "id": m.id, "topic": m.topic, "text": m.text,
                "trust": round(m.trust, 3), "status": m.status,
            })
            sentry_sdk.capture_message(
                f"IMMUNE quarantined poisoned memory {m.id} ({m.source})",
                level="warning",
            )
    except Exception:
        pass
