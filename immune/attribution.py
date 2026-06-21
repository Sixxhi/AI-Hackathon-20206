"""Scalable attribution by adaptive group testing + delta-debugging.

The problem with the v1 approach (try singles, then pairs, capped at r=2):

  1. Cost is O(N^2) replays and grows with retrieval width.
  2. A fixed subset size r is DEFEATED by k-redundant poison: plant r+1
     identical poison memories and no r-subset removal flips the answer, so the
     culprit is never found. Raising r just moves the wall.

Instead we find the MINIMAL set of memories whose removal flips fail->pass:

  - ADAPTIVE PEEL (group testing): order candidates most-suspect-first, then
    remove them one at a time until the answer flips to correct. The predicate is
    NON-MONOTONE — remove too few poisons and it stays wrong; remove too many and
    you also delete the true memory, collapsing the answer to "i don't know" — so
    a binary search on prefix length is invalid. With good suspicion ordering the
    peel stops after ~D removals (D = number of culprits) and never touches the
    trusted memory (ordered last).

  - DDMIN SHRINK (delta debugging, Zeller): shrink that passing set to a
    1-minimal flipping set by dropping any element that isn't needed. This
    GUARANTEES minimality regardless of suspicion order (a good memory peeled
    early is added back / spared), and catches redundant/colluding poison that
    fixed-r ablation cannot.

CRITICAL INVARIANT: the only thing this module calls is `replay_fn(exclude)`, a
DETERMINISTIC re-execution. No LLM, no network, no judge is in the blame path —
the verdict is "removing exactly these memories flips the failure," proven, not
guessed.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

# replay_fn(excluded_ids) -> True if the turn is CORRECT when those ids are removed.
ReplayFn = Callable[[frozenset], bool]
# suspicion_key(mem_id) -> sortable; LOWER = more suspect (tested for removal first).
SuspicionKey = Callable[[str], object]


class Attributor:
    def __init__(self, replay_fn: ReplayFn, suspicion_key: Optional[SuspicionKey] = None):
        self.replay_fn = replay_fn
        self.suspicion_key = suspicion_key
        self.replays = 0          # instrumentation: how many re-executions this cost

    def _passes(self, exclude: Iterable[str]) -> bool:
        self.replays += 1
        return self.replay_fn(frozenset(exclude))

    def attribute(self, admitted_ids: list[str]) -> tuple[list[str], str]:
        """Return (culprit_ids, confidence) where confidence in {high, medium, low}.

        high   -> a single memory is the culprit (its removal alone flips it)
        medium -> a minimal *set* (redundant / interacting poison) is the culprit
        low    -> no removal of memories yields the correct answer (not
                  memory-attributable; caller should soft-decay, not quarantine)
        """
        self.replays = 0
        if not admitted_ids:
            return [], "low"
        if self._passes([]):
            return [], "none"                           # not actually failing

        # most-suspect-first. The structure is NON-MONOTONE ("peak"): removing too
        # few poisons leaves the failure; removing too many also deletes the true
        # memory and the answer collapses to "i don't know". So we can't binary
        # search prefix length — we PEEL.
        if self.suspicion_key is not None:
            cands = sorted(admitted_ids, key=self.suspicion_key)
        else:
            cands = list(admitted_ids)

        # 1) ADAPTIVE PEEL: remove most-suspect memories one at a time until the
        #    answer flips to correct. With good suspicion ordering this stops after
        #    ~D removals (D = number of culprits), and never touches the trusted
        #    memory because it's ordered last.
        excluded: list[str] = []
        flipped = False
        for mid in cands:
            excluded.append(mid)
            if self._passes(excluded):
                flipped = True
                break
        if not flipped:
            return [], "low"                            # no removal yields correct

        # 2) DDMIN SHRINK to a 1-minimal flipping set (delta debugging). Drops any
        #    element not required — this self-corrects any over-peeling and
        #    GUARANTEES minimality regardless of the suspicion order, so a good
        #    memory that got peeled early is added back (spared) here.
        minimal = list(excluded)
        for mid in list(excluded):
            trial = [x for x in minimal if x != mid]
            if trial and self._passes(trial):
                minimal = trial
        minimal_set = set(minimal)
        culprits = [m for m in cands if m in minimal_set]

        conf = "high" if len(culprits) == 1 else "medium"
        return culprits, conf
