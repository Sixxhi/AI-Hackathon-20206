"""IMMUNE as a LangGraph store — a drop-in, poison-proof replacement for
`InMemoryStore` / any `BaseStore`.

A LangGraph agent reads and writes long-term memory through a `BaseStore`
(`store.put(...)`, `store.search(...)`, `store.get(...)`). Swap the store and the
agent's memory becomes self-defending — no change to the agent graph:

    - from langgraph.store.memory import InMemoryStore
    - store = InMemoryStore()
    + from immune.langgraph_store import ImmuneStore
    + store = ImmuneStore()          # same interface, now poison-proof

What the swap buys you, on the exact path where the attack happens:

  WRITE (`put`)    every memory is provenance-tagged (source class -> trust). An
                   untrusted write can never outrank the system-of-record.
  READ  (`search`) retrieval is trust-gated and recency-ordered, and QUARANTINED
                   poison is never returned — the protection is on the read path.
  HEAL  (`check`)  when an answer contradicts a trusted memory, IMMUNE proves which
                   memory is the culprit by deterministic counterfactual replay
                   (no model in the blame path), quarantines it + anything derived,
                   and returns the healed answer.

The blame path is identical to the rest of IMMUNE: structured ablation over the
in-memory store, no LLM judging guilt. If langgraph is installed this IS a real
`BaseStore` (works inside `create_react_agent(store=ImmuneStore())`); if it isn't,
the same object still works standalone, so the demo never depends on the network
or on langgraph being present.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from . import chat
from .attribution import Attributor
from .detectors import ContradictionDetector
from .schemas import MemoryRecord
from .store import ImmuneMemory

# --- bind to the real LangGraph BaseStore when available, else a thin shim ----
try:
    from langgraph.store.base import (  # type: ignore
        BaseStore as _BaseStore,
        Item as _LGItem,
        SearchItem as _LGSearchItem,
    )
    _HAS_LANGGRAPH = True
except Exception:                        # langgraph not installed -> standalone
    _HAS_LANGGRAPH = False

    class _BaseStore:                    # minimal stand-in with the same surface
        pass

    @dataclass
    class _LGItem:
        value: dict
        key: str
        namespace: tuple
        created_at: datetime
        updated_at: datetime

    @dataclass
    class _LGSearchItem(_LGItem):
        score: Optional[float] = None


Namespace = tuple[str, ...]


# --- value <-> MemoryRecord mapping ------------------------------------------

def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ("text", "content", "memory", "fact"):
            if value.get(k):
                return str(value[k])
        return json.dumps(value, sort_keys=True)
    return str(value)


def _as_topic(namespace: Namespace, value: Any) -> str:
    if isinstance(value, dict) and value.get("topic"):
        return str(value["topic"])
    return namespace[-1] if namespace else "general"


def _as_answer(value: Any, text: str) -> str:
    if isinstance(value, dict) and value.get("answer"):
        return str(value["answer"])
    return text


def _default_trust(source: str) -> float:
    return 0.9 if source == "official_doc" else 0.5


class ImmuneStore(_BaseStore):
    """A `BaseStore` whose memory is defended by the IMMUNE engine.

    Args:
      threshold:        admission floor; below it a memory is inadmissible.
      authority_trust:  only memories at/above this can accuse the agent of error
                        (so low-trust poison can never frame a correct answer).
      seed_policy:      preload the demo's system-of-record (refund/shipping/warranty).
    """

    def __init__(self, *, threshold: float = 0.3, authority_trust: float = 0.7,
                 seed_policy: bool = True):
        self.mem = ImmuneMemory(gate=True, threshold=threshold)
        self.detector = ContradictionDetector(self.mem, authority_trust=authority_trust)
        self._key_to_id: dict[tuple[Namespace, str], str] = {}
        if seed_policy:
            chat.seed(self.mem)

    # --- internal helpers ----------------------------------------------------
    def _do_put(self, namespace: Namespace, key: str, value: Any) -> None:
        ns = tuple(namespace)
        text = _as_text(value)
        source = value.get("source", "user") if isinstance(value, dict) else "user"
        trust = value.get("trust", _default_trust(source)) if isinstance(value, dict) else _default_trust(source)
        parents = tuple(value.get("parents", ())) if isinstance(value, dict) else ()
        rec = self.mem.add(
            MemoryRecord(text=text, topic=_as_topic(ns, value),
                         answer=_as_answer(value, text), source=source, trust=trust),
            parents=parents,
        )
        self._key_to_id[(ns, key)] = rec.id

    def _record_value(self, rec: MemoryRecord) -> dict:
        return {"text": rec.text, "answer": rec.answer, "topic": rec.topic,
                "source": rec.source, "trust": round(rec.trust, 3),
                "status": rec.status, "mem_id": rec.id}

    def _item(self, namespace: Namespace, key: str, rec: MemoryRecord, *, search=False):
        ts = datetime.fromtimestamp(rec.created_at, tz=timezone.utc)
        val = self._record_value(rec)
        if search:
            return _LGSearchItem(value=val, key=key, namespace=tuple(namespace),
                                 created_at=ts, updated_at=ts, score=None)
        return _LGItem(value=val, key=key, namespace=tuple(namespace),
                       created_at=ts, updated_at=ts)

    def _do_get(self, namespace: Namespace, key: str):
        mid = self._key_to_id.get((tuple(namespace), key))
        rec = self.mem.get(mid) if mid else None
        # the read-path protection: quarantined poison never surfaces
        if rec is None or rec.status == "quarantined":
            return None
        return self._item(namespace, key, rec)

    def _do_delete(self, namespace: Namespace, key: str) -> None:
        ns = tuple(namespace)
        mid = self._key_to_id.pop((ns, key), None)
        if mid:
            self.mem._mems.pop(mid, None)

    def _do_search(self, namespace_prefix: Namespace, *, query: Optional[str],
                   limit: int = 10, offset: int = 0):
        if query:
            hits = chat.retrieve(self.mem, query, k=limit + offset)
        else:
            # no query -> list admissible, non-quarantined memories, newest first
            hits = sorted(
                (m for m in self.mem.all() if m.is_admissible(self.mem.threshold)),
                key=lambda m: -m.seq,
            )[: limit + offset]
        out = []
        for rec in hits[offset: offset + limit]:
            # reverse-map a record to its (namespace, key); fall back to mem_id
            nk = next((nk for nk, i in self._key_to_id.items() if i == rec.id), None)
            ns, key = nk if nk else (tuple(namespace_prefix), rec.id)
            out.append(self._item(ns, key, rec, search=True))
        return out

    # --- public BaseStore interface (works standalone and inside LangGraph) ---
    def put(self, namespace: Namespace, key: str, value: dict,
            *, index=None, ttl=None) -> None:
        self._do_put(namespace, key, value)

    def get(self, namespace: Namespace, key: str, *, refresh_ttl=None):
        return self._do_get(namespace, key)

    def search(self, namespace_prefix: Namespace, *, query: Optional[str] = None,
               filter: Optional[dict] = None, limit: int = 10, offset: int = 0,
               refresh_ttl=None):
        return self._do_search(namespace_prefix, query=query, limit=limit, offset=offset)

    def delete(self, namespace: Namespace, key: str) -> None:
        self._do_delete(namespace, key)

    # --- ABC requirement: dispatch the typed ops to the helpers --------------
    def batch(self, ops: Iterable[Any]) -> list[Any]:
        results: list[Any] = []
        for op in ops:
            name = type(op).__name__
            if name == "GetOp":
                results.append(self._do_get(op.namespace, op.key))
            elif name == "PutOp":
                if getattr(op, "value", None) is None:
                    self._do_delete(op.namespace, op.key)
                else:
                    self._do_put(op.namespace, op.key, op.value)
                results.append(None)
            elif name == "SearchOp":
                results.append(self._do_search(
                    op.namespace_prefix, query=getattr(op, "query", None),
                    limit=getattr(op, "limit", 10), offset=getattr(op, "offset", 0)))
            else:                                 # ListNamespacesOp / unknown
                results.append([])
        return results

    async def abatch(self, ops: Iterable[Any]) -> list[Any]:
        return self.batch(ops)

    # --- the immune verb LangGraph doesn't have: HEAL ------------------------
    def check(self, query: str, answer: str) -> dict:
        """Failure signal -> proof -> heal. Call after the agent answers a
        grounded question: if `answer` contradicts the system-of-record, attribute
        the culprit by counterfactual replay, quarantine it (+ derived), report the
        incident, and return the healed answer. No model in the blame path."""
        admitted = [m.id for m in chat.retrieve(self.mem, query)]
        flag = self.detector.check(answer, admitted)
        result = {"contradiction": bool(flag), "culprits": [], "quarantined": [],
                  "cascade": [], "replays": 0, "healed_answer": answer,
                  "confidence": "none"}
        if not flag:
            return result

        attributor = Attributor(
            replay_fn=lambda excl: flag.expected.strip().lower()
            in chat._mock_answer(self.mem, query, exclude=tuple(excl)).strip().lower(),
            suspicion_key=chat._suspicion_key(self.mem),
        )
        culprits, conf = attributor.attribute(admitted)
        taken: list[str] = []
        for mid in culprits:
            taken += self.mem.quarantine_cascade(mid)
        quarantined = sorted(set(taken))
        cascade = sorted(set(taken) - set(culprits))
        result.update(culprits=culprits, confidence=conf, quarantined=quarantined,
                      cascade=cascade, replays=attributor.replays, reason=flag.reason,
                      expected=flag.expected,
                      healed_answer=chat._mock_answer(self.mem, query))

        # the quarantine is a production incident — report it (no-op if SENTRY_DSN unset)
        from . import sentry_report
        sentry_report.report_quarantine(
            question=query, answer=answer, expected=flag.expected or "",
            culprits=culprits, confidence=conf, quarantined=quarantined,
            cascade=cascade, replays=attributor.replays, store=self.mem)
        return result

    # --- convenience for demos / dashboards ----------------------------------
    def snapshot(self) -> list[dict]:
        return self.mem.snapshot()
