"""ShadowReplay — the moat (P1).

Attribution and parole are ONE engine: offline counterfactual replay against
logged failed turns. No LLM judge in the blame path (kills 'your judge is also
wrong'); no live re-test (kills 're-poison to find out it's poison').

  attribute()  -> remove a memory, replay the failure, did it flip to correct?
  parole()     -> re-admit a quarantined memory, replay its failures offline,
                  release ONLY if it no longer reproduces them.
"""
from __future__ import annotations

from itertools import combinations

from .agent import Agent, score
from .schemas import TurnLog
from .store import ImmuneMemory


class ShadowReplay:
    def __init__(self, store: ImmuneMemory, max_subset: int = 2):
        self.store = store
        self.agent = Agent(store)
        self.max_subset = max_subset          # singles + pairs (interaction effects)
        self.failed_log: list[TurnLog] = []   # ground-truth-bearing failures to replay against

    # --- core: replay one turn under a counterfactual exclusion ---------------
    def replay(self, question: str, expected: str, exclude: tuple[str, ...] = ()) -> bool:
        # Attribution must be DETERMINISTIC: always replay with the mock backend,
        # never the live LLM — even in IMMUNE_LIVE mode. A nondeterministic answer
        # here would make the culprit set flicker and put a model in the blame path
        # (the exact thing this engine exists to avoid). See ARCHITECTURE.md.
        ans, _ = self.agent._answer_mock(question, exclude)
        return score(ans, expected)

    # --- attribution by ablation (not by a fallible judge) --------------------
    def attribute(self, turn: TurnLog) -> tuple[list[str], str]:
        """Return (culprit_ids, confidence). confidence in {high, medium, low}."""
        admitted = turn.admitted_ids
        # singles: a removal that flips fail->pass is an empirical culprit
        singles = [mid for mid in admitted
                   if self.replay(turn.question, turn.expected, exclude=(mid,))]
        if singles:
            return singles, "high"
        # pairs: interaction effects (two innocent-looking memories combine wrong)
        for r in range(2, self.max_subset + 1):
            for combo in combinations(admitted, r):
                if self.replay(turn.question, turn.expected, exclude=combo):
                    return list(combo), "medium"
        return [], "low"   # ambiguous -> do NOT quarantine

    # --- failure handling: confidence-gated ----------------------------------
    def handle_failure(self, turn: TurnLog) -> dict:
        culprits, conf = self.attribute(turn)
        self.failed_log.append(turn)
        action: dict = {"turn": turn.id, "confidence": conf, "culprits": culprits}

        if conf == "high":
            for mid in culprits:
                self.store.quarantine(mid)
            action["action"] = "quarantine"
        elif conf == "medium":
            # combine-wrong: quarantine the self-generated/lowest-trust one, decay rest
            ranked = sorted(culprits, key=lambda mid: self.store.get(mid).trust)
            self.store.quarantine(ranked[0])
            for mid in ranked[1:]:
                self.store.decay(mid, alpha=0.3)
            action["action"] = "quarantine+decay"
        else:
            # ambiguous: soft-decay only, quarantine nothing (anti-autoimmune)
            for mid in turn.admitted_ids:
                self.store.decay(mid, alpha=0.15)
            action["action"] = "soft-decay"
        return action

    # --- parole: offline re-trial, same engine -------------------------------
    def parole(self) -> list[str]:
        paroled: list[str] = []
        for m in self.store.quarantined():
            blamed = [t for t in self.failed_log if m.id in t.admitted_ids]
            if not blamed:
                continue
            # temporarily re-admit and replay its failures offline (shadow sandbox)
            prev_status, prev_trust = m.status, m.trust
            m.status, m.trust = "active", self.store.threshold + 0.1
            still_fails = any(
                not self.replay(t.question, t.expected) for t in blamed
            )
            if still_fails:
                m.status, m.trust = prev_status, prev_trust   # stays in jail
            else:
                self.store.parole(m.id)                       # release — proven safe
                paroled.append(m.id)
        return paroled
