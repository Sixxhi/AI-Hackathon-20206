"""Agent: answers questions from memory (P3).

Mock backend is default (zero network, instantly demoable).
Set ANTHROPIC_API_KEY to flip to the live Claude backend.

Swap targets:
  route_topic()  → semantic embedding/Claude routing (replaces keyword map)
  answer()       → real Claude call with memory context as grounding
"""
from __future__ import annotations

from .schemas import MemoryRecord, TurnLog
from .store import ImmuneMemory
from . import config

# keyword router — used by mock and as fallback when Claude can't route
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
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def answer(self, question: str, exclude: tuple[str, ...] = ()) -> tuple[str, list[str]]:
        if config.USE_CLAUDE:
            return self._answer_claude(question, exclude)
        return self._answer_mock(question, exclude)

    def _answer_mock(self, question: str, exclude: tuple[str, ...]) -> tuple[str, list[str]]:
        topic = route_topic(question)
        if topic is None:
            return "i don't know", []
        hits = self.store.search(topic, exclude=exclude)
        if not hits:
            return "i don't know", []
        chosen = hits[0]
        return chosen.answer, [m.id for m in hits]

    def _answer_claude(self, question: str, exclude: tuple[str, ...]) -> tuple[str, list[str]]:
        """Live Claude answer grounded in admissible memories."""
        # still use keyword routing to scope retrieval; swap for embeddings later
        topic = route_topic(question)
        hits = self.store.search(topic, exclude=exclude) if topic else []

        if not hits:
            return "i don't know", []

        memory_context = "\n".join(f"- {m.text}" for m in hits)

        client = self._get_client()
        response = client.messages.create(
            model=config.AGENT_MODEL,
            max_tokens=64,
            system=(
                "You are a customer support agent. Answer the customer using your "
                "stored memory below. Follow your memory. Reply in one short sentence."
            ),
            messages=[{
                "role": "user",
                "content": f"Your memory:\n{memory_context}\n\nCustomer question: {question}",
            }],
        )
        if response.stop_reason == "refusal":
            # safety classifier declined — surface, don't crash on empty content
            return "i don't know", [m.id for m in hits]
        # content[0] isn't guaranteed to be the text block (thinking can lead);
        # pick the first text block instead of indexing blindly.
        answer = next((b.text for b in response.content if b.type == "text"), "").strip()
        return answer, [m.id for m in hits]


def score(answer: str, expected: str) -> bool:
    """Ground-truth grader. Benchmark-only EVAL signal (not a prod dashboard)."""
    return expected.strip().lower() in answer.strip().lower()
