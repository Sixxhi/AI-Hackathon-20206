"""Deterministic mock agent + scorer (P3).

No network — runs with zero API keys so v1 is instantly demoable.
Swap `interpret()` and `answer()` internals for Claude calls later; keep signatures.
"""
from __future__ import annotations

from .schemas import MemoryRecord, TurnLog
from .store import ImmuneMemory

# minimal topic router: maps question keywords -> topic. Swap -> embedding/Claude.
_TOPICS = {
    "refund": "refund_window",
    "return": "refund_window",
    "ship": "shipping_time",
    "delivery": "shipping_time",
    "warranty": "warranty_len",
}


def route_topic(text: str) -> str | None:
    t = text.lower()
    for kw, topic in _TOPICS.items():
        if kw in t:
            return topic
    return None


class Agent:
    """Answers questions from memory. Picks newest admissible memory for the topic."""

    def __init__(self, store: ImmuneMemory):
        self.store = store

    def answer(self, question: str, exclude: tuple[str, ...] = ()) -> tuple[str, list[str]]:
        topic = route_topic(question)
        if topic is None:
            return "i don't know", []
        hits = self.store.search(topic, exclude=exclude)
        if not hits:
            return "i don't know", []
        chosen = hits[0]                      # newest admissible
        return chosen.answer, [m.id for m in hits]

    # --- organic self-poisoning -------------------------------------------
    def ingest_ambiguous(self, raw: str) -> MemoryRecord:
        """Agent INFERS a (wrong) fact from ambiguous input and stores it itself.
        Not injected by us -> kills the 'rigged demo' smell. Both agents call this.
        """
        # "switched to the 90" is ambiguous: 90-day plan vs $90 plan.
        # The agent wrongly infers refund window = 90 days (truth = 30).
        guess = "90 days" if "90" in raw else "unknown"
        return MemoryRecord(
            text=f"(self-inferred from: '{raw}') refund window is {guess}",
            topic="refund_window",
            answer=guess,
            source="self_generated",
            trust=0.5,
        )


def score(answer: str, expected: str) -> bool:
    """Ground-truth grader. Benchmark-only EVAL signal (not a prod dashboard)."""
    return answer.strip().lower() == expected.strip().lower()
