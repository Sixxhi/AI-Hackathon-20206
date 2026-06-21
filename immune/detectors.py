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


import re

# word-numbers and unit synonyms — enough to recognize that "thirty days" == "30 days"
# and "fifty megabytes" == "50 MB" without an LLM, deterministically.
_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
          "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
          "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
          "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
          "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
          "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100"}
_UNITS = {"megabytes": "mb", "megabyte": "mb", "mb": "mb", "gigabytes": "gb",
          "gigabyte": "gb", "gb": "gb", "kilobytes": "kb", "kilobyte": "kb", "kb": "kb",
          "terabytes": "tb", "terabyte": "tb", "tb": "tb", "days": "day", "day": "day",
          "weeks": "week", "week": "week", "months": "month", "month": "month",
          "years": "year", "year": "year", "hours": "hour", "hour": "hour",
          "minutes": "min", "minute": "min"}


def _canon(s: str) -> str:
    """Lowercase, drop punctuation (keep @ . for emails), map word-numbers + units."""
    s = re.sub(r"[^a-z0-9@.\s]", " ", s.strip().lower())
    return " ".join(_UNITS.get(_WORDS.get(w, w), _WORDS.get(w, w)) for w in s.split())


def _value_tokens(canon: str) -> set:
    """Normalized number+unit values, e.g. {'30day', '50mb'} — the salient claim."""
    return {f"{n}{u}" for n, u in
            re.findall(r"\b(\d+)\s*(mb|gb|kb|tb|day|week|month|year|hour|min)\b", canon)}


def _claims_match(answer: str, claim: str) -> bool:
    """Does the answer ASSERT the authority's claim? Value-aware, not raw substring.

    If the claim states concrete value(s) (e.g. '30 days'), the answer agrees only
    if every such value appears in it after normalization — so 'thirty days' and
    '50 MB' match their digit forms, while '90 days'/'5 GB' (and '500MB' vs '50MB')
    correctly do NOT. Non-numeric claims fall back to normalized containment.
    """
    ca, cc = _canon(answer), _canon(claim)
    if not cc:
        return False
    claim_vals = _value_tokens(cc)
    if claim_vals:
        return claim_vals <= _value_tokens(ca)
    return cc in ca or ca in cc


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


class LLMContradictionDetector:
    """Semantic contradiction check for fuzzy paraphrase ('one month' vs '30 days')
    that the value-aware matcher can't resolve. Uses an LLM ONLY to decide *whether
    to investigate* — it is never in the blame path (attribution stays deterministic
    replay). Falls back to the deterministic detector with no key / on any error, so
    behavior degrades safely and offline stays green.
    """

    def __init__(self, store: ImmuneMemory, authority_trust: float = 0.7, model: str = ""):
        self.store = store
        self.authority_trust = authority_trust
        self.model = model
        self._client = None
        self._fallback = ContradictionDetector(store, authority_trust)

    def _authority(self, admitted_ids: list[str]):
        auth = [m for m in (self.store.get(i) for i in admitted_ids)
                if m and m.source == "official_doc" and m.trust >= self.authority_trust]
        return max(auth, key=lambda m: m.trust) if auth else None

    def check(self, answer: str, admitted_ids: list[str]) -> Suspicion:
        authority = self._authority(admitted_ids)
        if authority is None:
            return Suspicion(False)
        from . import config
        try:
            if self._client is None:
                import anthropic
                self._client = anthropic.Anthropic()
            resp = self._client.messages.create(
                model=self.model or config.JUDGE_MODEL, max_tokens=8,
                system=("Reply with exactly one word — CONSISTENT or CONTRADICTS — for "
                        "whether the candidate answer contradicts the policy fact."),
                messages=[{"role": "user",
                           "content": f"Policy fact: {authority.answer}\nCandidate answer: {answer}"}])
            verdict = next((b.text for b in resp.content if b.type == "text"), "").upper()
        except Exception:
            return self._fallback.check(answer, admitted_ids)   # no key / network → deterministic
        if "CONTRADICT" in verdict:
            return Suspicion(True, reason=f"LLM judged contradiction with {authority.id}: "
                             f"{authority.answer!r}", authority_id=authority.id,
                             expected=authority.answer)
        return Suspicion(False)
