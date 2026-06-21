"""IMMUNE as an MCP server — plug self-healing memory into ANY MCP agent
(Claude Code, Claude Desktop, etc.).

The agent uses IMMUNE as its long-term memory through four tools:

  immune_remember(text, source)  -> store a fact (provenance + initial trust)
  immune_recall(query)           -> retrieve facts to ground an answer. Quarantined
                                    poison NEVER surfaces — this is the protection.
  immune_check(query, answer)    -> failure signal: if the answer contradicts a
                                    trusted memory, attribute the culprit by
                                    deterministic replay, quarantine it (+ derived),
                                    and return the healed answer.
  immune_status()                -> current memory, trust, and quarantine state.

EVERY call is appended to a JSONL audit log (IMMUNE_RECORD_PATH, default
./immune_record.jsonl) — that's your recording of the agent's memory being
poisoned and healed on real traffic. Memory persists to IMMUNE_STORE_PATH so it
survives restarts (defends the cross-session persistence threat).

The blame path stays deterministic: attribution re-runs over IMMUNE's structured
memory with a fixed answer proxy — no model judges who is guilty.

Run:   python -m immune.mcp_server
Plug:  claude mcp add immune -- python -m immune.mcp_server
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import chat
from .attribution import Attributor
from .detectors import ContradictionDetector
from .schemas import MemoryRecord
from .store import ImmuneMemory

_RECORD_PATH = os.getenv("IMMUNE_RECORD_PATH", "immune_record.jsonl")
_STORE_PATH = os.getenv("IMMUNE_STORE_PATH", "immune_store.json")


class Engine:
    """Holds the memory + detector and does the record/persist bookkeeping.

    Kept separate from the MCP wrappers so it is unit-testable without a transport.
    """

    def __init__(self, store: ImmuneMemory | None = None, seed: bool = True):
        self.store = store or ImmuneMemory(gate=True, threshold=0.3)
        if seed and not self.store.all():
            self._load() or (chat.seed(self.store))
        self.detector = ContradictionDetector(self.store)

    # --- persistence + recording --------------------------------------------
    def _record(self, op: str, payload: dict) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(), "op": op, **payload}
        try:
            with open(_RECORD_PATH, "a") as f:
                f.write(json.dumps(line) + "\n")
        except Exception:
            pass

    def _save(self) -> None:
        try:
            with open(_STORE_PATH, "w") as f:
                json.dump(self.store.snapshot(), f)
        except Exception:
            pass

    def _load(self) -> bool:
        if not os.path.exists(_STORE_PATH):
            return False
        try:
            for m in json.load(open(_STORE_PATH)):
                rec = MemoryRecord(text=m["text"], topic=m.get("topic", "general"),
                                   answer=m.get("answer", ""), source=m["source"],
                                   trust=m["trust"], status=m["status"])
                self.store.add(rec)
            return True
        except Exception:
            return False

    # --- the four operations -------------------------------------------------
    def remember(self, text: str, source: str = "user", answer: str = "",
                 topic: str = "general") -> dict:
        rec = self.store.add(MemoryRecord(text=text, topic=topic, answer=answer or text,
                                          source=source, trust=0.9 if source == "official_doc" else 0.5))
        self._save()
        out = {"id": rec.id, "source": rec.source, "trust": rec.trust}
        self._record("remember", {"text": text, **out})
        return out

    def recall(self, query: str, k: int = 4) -> dict:
        hits = chat.retrieve(self.store, query, k=k)            # gated: poison filtered
        out = {"memories": [{"id": m.id, "text": m.text, "source": m.source,
                             "trust": round(m.trust, 3)} for m in hits]}
        self._record("recall", {"query": query, "returned": [m.id for m in hits]})
        return out

    def check(self, query: str, answer: str) -> dict:
        admitted = [m.id for m in chat.retrieve(self.store, query)]
        flag = self.detector.check(answer, admitted)
        result = {"contradiction": bool(flag), "culprits": [], "quarantined": [],
                  "healed_answer": answer}
        if flag:
            attributor = Attributor(
                replay_fn=lambda excl: flag.expected.strip().lower()
                in chat._mock_answer(self.store, query, exclude=tuple(excl)).strip().lower(),
                suspicion_key=chat._suspicion_key(self.store))
            culprits, conf = attributor.attribute(admitted)
            taken: list[str] = []
            for mid in culprits:
                taken += self.store.quarantine_cascade(mid)
            self._save()
            result.update(culprits=culprits, confidence=conf,
                          quarantined=sorted(set(taken)),
                          replays=attributor.replays,
                          reason=flag.reason,
                          healed_answer=chat._mock_answer(self.store, query))
        self._record("check", {"query": query, "answer": answer, **result})
        return result

    def status(self) -> dict:
        snap = self.store.snapshot()
        return {"total": len(snap),
                "quarantined": [m for m in snap if m["status"] == "quarantined"],
                "active": [m for m in snap if m["status"] == "active"]}


def build_server():
    # the official MCP SDK ships FastMCP; the slim `fastmcp` pkg has no server.
    from mcp.server.fastmcp import FastMCP
    engine = Engine()
    mcp = FastMCP("immune")

    @mcp.tool()
    def immune_remember(text: str, source: str = "user") -> dict:
        """Store a fact in long-term memory. source: official_doc|user|web|tool."""
        return engine.remember(text, source=source)

    @mcp.tool()
    def immune_recall(query: str) -> dict:
        """Retrieve memories to ground an answer. Quarantined poison is excluded."""
        return engine.recall(query)

    @mcp.tool()
    def immune_check(query: str, answer: str) -> dict:
        """Check an answer against the system-of-record. If it contradicts a trusted
        memory, attribute + quarantine the culprit and return the healed answer."""
        return engine.check(query, answer)

    @mcp.tool()
    def immune_status() -> dict:
        """Show current memory: active vs quarantined, with trust scores."""
        return engine.status()

    return mcp


def main():
    build_server().run()


if __name__ == "__main__":
    main()
