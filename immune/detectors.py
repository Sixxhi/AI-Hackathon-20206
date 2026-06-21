"""Failure signals WITHOUT ground truth — the production trigger.

In the benchmark we have `expected`, so we know a turn failed. In production you
almost never do: if the app knew the answer was wrong it wouldn't need the
agent. So the engine that wakes attribution must run on signals you actually own.

The strongest automatic one — and the only one used by default here — is
CONTRADICTION WITH A HIGHER-TRUST MEMORY:

  the agent's answer disagrees with an authoritative (official / system-of-record)
  memory on the same topic that was in scope for this turn.

That is a label you own: provenance gives you the authority, the answer gives you
the claim, and disagreement between them is grounds to replay. No oracle, no
human, no second LLM required.

Two oracle-free detectors live here: `ContradictionDetector` (default) and
`SelfConsistencyDetector` (re-ask N times; instability ⇒ suspect). Either way, a
detector only decides *whether to investigate* — it is never in the blame path
(`ShadowReplay` proves *who is guilty* by deterministic replay).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .store import ImmuneMemory


@dataclass
class Suspicion:
    suspicious: bool
    reason: str = ""
    authority_id: Optional[str] = None      # the trusted memory the answer contradicts
    expected: Optional[str] = None          # what the authority says (the replay target)

    def __bool__(self) -> bool:
        return self.suspicious


def _claims_match(answer: str, claim: str) -> bool:
    """Loose containment: does the answer assert the authority's claim?"""
    a, c = answer.strip().lower(), claim.strip().lower()
    return bool(c) and (c in a or a in c)


class ContradictionDetector:
    """Flags a turn when the answer contradicts the highest-trust in-scope memory.

    `authority_trust` is the bar for "authoritative" — only memories at/above it
    can accuse the agent of being wrong, so a low-trust poison can never frame a
    correct answer as a failure.
    """

    def __init__(self, store: ImmuneMemory, authority_trust: float = 0.7):
        self.store = store
        self.authority_trust = authority_trust

    def check(self, answer: str, admitted_ids: list[str]) -> Suspicion:
        admitted = [self.store.get(m) for m in admitted_ids]
        authorities = [m for m in admitted
                       if m and m.source == "official_doc" and m.trust >= self.authority_trust]
        if not authorities:
            return Suspicion(False)                      # nothing trusted to contradict
        authority = max(authorities, key=lambda m: m.trust)
        if _claims_match(answer, authority.answer):
            return Suspicion(False)                      # answer agrees with authority
        return Suspicion(
            True,
            reason=(f"answer {answer!r} contradicts trusted memory "
                    f"{authority.id} (trust={authority.trust:.2f}): {authority.answer!r}"),
            authority_id=authority.id,
            expected=authority.answer,
        )


class SelfConsistencyDetector:
    """Flags a turn when re-asking yields a different answer (instability ~ poison).

    Cheap, oracle-free second signal: ask the same question `n` times; if the
    agent can't agree with itself, something in memory is unstable. `answer_fn`
    is any callable question->answer (the live agent).
    """

    def __init__(self, answer_fn, n: int = 3):
        self.answer_fn = answer_fn
        self.n = n

    def check(self, question: str) -> Suspicion:
        answers = {self.answer_fn(question).strip().lower() for _ in range(self.n)}
        if len(answers) <= 1:
            return Suspicion(False)
        return Suspicion(True, reason=f"answer unstable across {self.n} asks: {answers}")
