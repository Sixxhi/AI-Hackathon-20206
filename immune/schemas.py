"""Locked interfaces.

Swap targets later:
  MemoryRecord.embedding -> real embedding vector (Redis vector field)
  These dataclasses map 1:1 onto Redis hashes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import itertools
import time

_ids = itertools.count(1)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{next(_ids)}"


@dataclass
class MemoryRecord:
    text: str                      # human-readable memory
    topic: str                     # what it's about (retrieval key); swap -> embedding match
    answer: str                    # the claim the agent would act on
    source: str                    # provenance: official_doc | self_generated | user | web | tool
    trust: float = 0.5             # mutable 0..1, the immune signal
    status: str = "active"         # active | quarantined
    created_at: float = field(default_factory=time.time)
    seq: int = field(default_factory=lambda: next(_ids))  # deterministic recency order
    id: str = field(default_factory=lambda: _new_id("mem"))

    def is_admissible(self, threshold: float) -> bool:
        return self.status == "active" and self.trust >= threshold


@dataclass
class TurnLog:
    question: str
    expected: str                  # ground truth (benchmark only — an EVAL signal, not prod)
    answer: str = ""               # what the agent actually said
    admitted_ids: list[str] = field(default_factory=list)  # what fed this turn -> enables replay
    correct: bool = False
    id: str = field(default_factory=lambda: _new_id("turn"))
