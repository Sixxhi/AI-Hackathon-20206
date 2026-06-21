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

# Default state under a stable home dir (not the launch cwd) so an external
# deployment doesn't litter whatever directory it was started from. Override per env.
_HOME = os.path.expanduser(os.getenv("IMMUNE_HOME", "~/.immune"))
_RECORD_PATH = os.getenv("IMMUNE_RECORD_PATH", os.path.join(_HOME, "record.jsonl"))
_STORE_PATH = os.getenv("IMMUNE_STORE_PATH", os.path.join(_HOME, "store.json"))


def _demo_seed_enabled() -> bool:
    return os.getenv("IMMUNE_DEMO_SEED", "").strip().lower() in ("1", "true", "yes")


class Engine:
    """Holds the memory + detector and does the record/persist bookkeeping.

    Kept separate from the MCP wrappers so it is unit-testable without a transport.
    """

    def __init__(self, store: ImmuneMemory | None = None, seed: bool = True):
        self.store = store or ImmuneMemory(gate=True, threshold=0.3)
        if not self.store.all():
            # Always try to restore persisted memory (cross-session). The demo facts
            # (refund/shipping/warranty) are loaded ONLY when seed=True — a real
            # external deployment passes seed=False and starts clean.
            if not self._load() and seed:
                chat.seed(self.store)
        self._load_official()                      # operator system-of-record (out-of-band)
        self.detector = ContradictionDetector(self.store)

    def _load_official(self) -> None:
        """Register the operator's system-of-record from IMMUNE_OFFICIAL_PATH — a JSON
        list of {text, answer, topic}. This is the out-of-band trusted channel: the
        operator ships the file; an in-band agent/attacker can't write to it, so it
        can't forge `official_doc`. Restores client-configurable anchors safely."""
        path = os.getenv("IMMUNE_OFFICIAL_PATH")
        if not path or not os.path.exists(path):
            return
        try:
            for f in json.load(open(path)):
                self.register_official(f["text"], answer=f.get("answer", ""),
                                       topic=f.get("topic", "general"))
        except Exception:
            pass

    # --- persistence + recording --------------------------------------------
    def _record(self, op: str, payload: dict) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(), "op": op, **payload}
        try:
            os.makedirs(os.path.dirname(_RECORD_PATH) or ".", exist_ok=True)
            with open(_RECORD_PATH, "a") as f:
                f.write(json.dumps(line) + "\n")
        except Exception:
            pass

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STORE_PATH) or ".", exist_ok=True)
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
                 topic: str = "general", trusted: bool = False) -> dict:
        # The trust LABEL is NOT caller-assertable on the agent-facing surface.
        # Otherwise an attacker just labels poison "official_doc" and the trust
        # hierarchy becomes an honor system. Only an operator registering the
        # system-of-record (trusted=True) may mint official_doc; everything an
        # agent writes is untrusted regardless of the source string it claims.
        if source == "official_doc" and not trusted:
            source = "user"
        rec = self.store.add(MemoryRecord(text=text, topic=topic, answer=answer or text,
                                          source=source, trust=0.9 if source == "official_doc" else 0.5))
        self._save()
        out = {"id": rec.id, "source": rec.source, "trust": rec.trust}
        self._record("remember", {"text": text, **out})
        return out

    def register_official(self, text: str, answer: str = "", topic: str = "general") -> dict:
        """Operator-only: register a system-of-record fact (the trusted channel an
        agent cannot forge). NOT exposed as an agent MCP tool."""
        return self.remember(text, source="official_doc", answer=answer, topic=topic, trusted=True)

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
            result.update(confidence=conf, reason=flag.reason, replays=attributor.replays)
            if culprits:
                taken: list[str] = []
                for mid in culprits:
                    taken += self.store.quarantine_cascade(mid)
                self._save()
                result.update(culprits=culprits, quarantined=sorted(set(taken)),
                              healed_answer=chat._mock_answer(self.store, query))
            else:
                # Flagged vs the system-of-record but NO memory is attributable
                # (paraphrase / semantic gap). Do NOT quarantine and do NOT
                # override the caller's answer — only flag it for review.
                result["action"] = "review"
                result["note"] = ("answer differs from the system-of-record but no "
                                  "stored memory is attributable — left for review, "
                                  "nothing quarantined or overridden")
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
    # External deployments start CLEAN: only persisted memory + operator anchors
    # (IMMUNE_OFFICIAL_PATH). The refund/shipping/warranty demo facts load only when
    # IMMUNE_DEMO_SEED=1, so the server isn't pre-polluted in real use.
    engine = Engine(seed=_demo_seed_enabled())
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

    admin_token = os.getenv("IMMUNE_ADMIN_TOKEN", "")

    @mcp.tool()
    def immune_register_official(text: str, answer: str = "", topic: str = "general",
                                 admin_token_arg: str = "") -> dict:
        """OPERATOR-ONLY: register a system-of-record fact (an anchor `check` defends).
        Requires the server's IMMUNE_ADMIN_TOKEN — so an agent/attacker driving these
        tools cannot forge trust. Operators can also seed anchors via IMMUNE_OFFICIAL_PATH.
        """
        if not admin_token or admin_token_arg != admin_token:
            return {"error": "register_official requires the operator IMMUNE_ADMIN_TOKEN "
                             "(set out-of-band on the server). Trust is not agent-assertable."}
        return engine.register_official(text, answer=answer, topic=topic)

    return mcp


def main():
    build_server().run()


if __name__ == "__main__":
    main()
