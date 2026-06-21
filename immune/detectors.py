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
import unicodedata

# word-numbers and unit synonyms — recognize "thirty days" == "30 days" etc.
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
_NEG = re.compile(r"\b(not|no|never|without|cannot|none|disabled|optional)\b|n't")


def _canon(s: str) -> str:
    """NFKC (fullwidth→ascii), lowercase, keep $ . @ ' , map word-numbers + units."""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = re.sub(r"[^a-z0-9@.$'\s]", " ", s)
    return " ".join(_UNITS.get(_WORDS.get(w, w), _WORDS.get(w, w)) for w in s.split())


def _values(canon: str) -> set:
    """Parsed (unit, number) pairs — compared by NUMERIC EQUALITY, not substring.
    Captures currency ($30 / 30 dollars), number+unit (50 mb), and bare numbers.
    So '5' != '15'/'50' and '$30' != '$300' (the superstring misses), while
    '$30.00' == '$30' and '50 mb' != '50 gb' (unit matters)."""
    vals = set()
    for amt in re.findall(r"\$\s*(\d+(?:\.\d+)?)", canon):
        vals.add(("$", float(amt)))
    for amt in re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:dollars?|usd|bucks?)\b", canon):
        vals.add(("$", float(amt)))
    for n, u in re.findall(r"\b(\d+(?:\.\d+)?)\s*(mb|gb|kb|tb|day|week|month|year|hour|min)\b", canon):
        vals.add((u, float(n)))
    for n in re.findall(r"\b(\d+(?:\.\d+)?)\b", canon):
        vals.add(("", float(n)))
    return vals


_FILLER = set(_UNITS.values()) | {"dollars", "dollar", "usd", "bucks", "buck", "$"}


def _is_value_claim(canon: str) -> bool:
    """True if the claim is essentially a numeric value (a number with only units/
    currency around it) — e.g. '5', '$30', '30 day', '50 mb'. False for names that
    merely contain a digit ('us east 1'), which must be compared as text."""
    if not re.search(r"\d", canon):
        return False
    leftover = [w for w in re.sub(r"\d+(?:\.\d+)?|\$", " ", canon).split() if w not in _FILLER]
    return not leftover


def _claims_match(answer: str, claim: str) -> bool:
    """Does the answer ASSERT the authority's claim?

    - Value claims ('5', '$30', '30 days', '50 MB'): every claimed (unit, value)
      must appear by *parsed numeric equality* — superstring numbers ('5' vs '15',
      '$30' vs '$300') no longer pass, and units must match ('50 mb' != '50 gb').
    - Everything else (names, booleans, emails): normalized containment, but
      **negation-aware** — 'not enabled' vs 'enabled' is a contradiction, not a match.
    """
    ca, cc = _canon(answer), _canon(claim)
    if not cc:
        return False
    if _is_value_claim(cc):
        return _values(cc) <= _values(ca)
    if not (cc in ca or ca in cc):
        return False
    return bool(_NEG.search(ca)) == bool(_NEG.search(cc))   # same polarity → agree


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
