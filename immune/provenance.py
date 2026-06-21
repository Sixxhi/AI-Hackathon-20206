"""Provenance & derivation lineage — chain-of-custody for memory.

Grounded in MemLineage (arXiv 2605.14421): memory poisoning is a chain-of-custody
problem, not a filtering problem. The dangerous case the literature names is
*distillation hides provenance* — an agent reads a poisoned memory, summarizes
or generalizes it into a new "clean-looking" rule, and the lineage back to the
poison is lost. Galileo (Dec 2025) measured the blast radius: one poisoned
memory contaminated 87% of downstream decisions within four hours.

So every memory may declare the parent memories it was DERIVED from. When
attribution names a culprit, we don't just quarantine that node — we walk the
derivation graph and quarantine the entire contaminated subtree, because a
memory distilled from poison is itself poison even when it reads as benign.

This module is pure bookkeeping (a DAG of memory ids). It holds no text and
makes no trust decisions; the store and the attributor consume it.
"""
from __future__ import annotations

from collections import deque
from typing import Iterable


class ProvenanceGraph:
    def __init__(self) -> None:
        self._parents: dict[str, set[str]] = {}
        self._children: dict[str, set[str]] = {}

    def add(self, mem_id: str, parents: Iterable[str] = ()) -> None:
        """Register a memory and the parents it was derived from (may be empty)."""
        self._parents.setdefault(mem_id, set())
        self._children.setdefault(mem_id, set())
        for p in parents:
            self._parents.setdefault(p, set())
            self._children.setdefault(p, set())
            self._parents[mem_id].add(p)
            self._children[p].add(mem_id)

    def parents(self, mem_id: str) -> set[str]:
        return set(self._parents.get(mem_id, ()))

    def children(self, mem_id: str) -> set[str]:
        return set(self._children.get(mem_id, ()))

    def roots(self) -> list[str]:
        """Memories with no recorded parent — the ground sources."""
        return [m for m, ps in self._parents.items() if not ps]

    def descendants(self, mem_id: str) -> set[str]:
        """Everything derived (transitively) from mem_id. Excludes mem_id itself."""
        seen: set[str] = set()
        q = deque(self._children.get(mem_id, ()))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(self._children.get(cur, ()))
        return seen

    def ancestors(self, mem_id: str) -> set[str]:
        """Everything mem_id was (transitively) derived from. The chain of custody."""
        seen: set[str] = set()
        q = deque(self._parents.get(mem_id, ()))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(self._parents.get(cur, ()))
        return seen

    def contaminated(self, culprits: Iterable[str]) -> set[str]:
        """The full quarantine set for a verdict: culprits + everything downstream.

        This is the cascade: cut the root and everything distilled from it falls
        with it, even nodes that look clean in isolation.
        """
        out: set[str] = set()
        for c in culprits:
            out.add(c)
            out |= self.descendants(c)
        return out
