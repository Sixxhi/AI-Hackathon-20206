"""ShadowReplay — the moat (P1).

Attribution and parole are ONE engine: offline counterfactual replay against
logged failed turns. No LLM judge in the blame path (kills 'your judge is also
wrong'); no live re-test (kills 're-poison to find out it's poison').

  attribute()  -> remove a memory, replay the failure, did it flip to correct?
  parole()     -> re-admit a quarantined memory, replay its failures offline,
                  release ONLY if it no longer reproduces them.
"""
from __future__ import annotations

from .agent import Agent, score
from .attribution import Attributor
from .schemas import TurnLog
from .store import ImmuneMemory


class ShadowReplay:
    def __init__(self, store: ImmuneMemory, max_subset: int = 2):
        self.store = store
        self.agent = Agent(store)
        self.max_subset = max_subset          # back-compat (group testing has no fixed cap)
        self.failed_log: list[TurnLog] = []   # ground-truth-bearing failures to replay against
        self.trust_history: list[dict] = []   # P1-1: trust snapshots per event (for the dashboard)
        self.last_replays = 0                 # replays the last attribution cost (instrumentation)
        self._record("start")                 # baseline before any failure

    def _suspicion_key(self, mid: str):
        """LOWER = more suspect, tested for removal first. Untrusted source, low
        trust, and recency all raise suspicion. Order only affects speed/choice
        among equally-minimal sets — never correctness (ddmin is 1-minimal)."""
        m = self.store.get(mid)
        if m is None:
            return (0, 0.0, 0)
        trusted_source = 1 if m.source == "official_doc" else 0
        return (trusted_source, m.trust, -m.seq)

    # --- P1-1: trust history for the dashboard --------------------------------
    def _record(self, turn) -> None:
        """Snapshot every memory's trust at this point in the run."""
        self.trust_history.append({"turn": turn, "snapshot": self.store.snapshot()})

    def trust_timeline(self) -> dict:
        """Reshape trust_history into {mem_id: [(turn, trust), ...]} for plotting."""
        series: dict = {}
        for entry in self.trust_history:
            for m in entry["snapshot"]:
                series.setdefault(m["id"], []).append((entry["turn"], m["trust"]))
        return series

    # --- core: replay one turn under a counterfactual exclusion ---------------
    def replay(self, question: str, expected: str, exclude: tuple[str, ...] = ()) -> bool:
        # Attribution must be DETERMINISTIC: always replay with the mock backend,
        # never the live LLM — even in IMMUNE_LIVE mode. A nondeterministic answer
        # here would make the culprit set flicker and put a model in the blame path
        # (the exact thing this engine exists to avoid). See ARCHITECTURE.md.
        ans, _ = self.agent._answer_mock(question, exclude)
        return score(ans, expected)

    # --- attribution by adaptive group testing (not by a fallible judge) ------
    def attribute(self, turn: TurnLog) -> tuple[list[str], str]:
        """Return (culprit_ids, confidence) via the group-testing Attributor.

        Finds the MINIMAL set of memories whose removal flips fail->pass: a
        single culprit (high), a redundant/interacting set (medium), or nothing
        memory-attributable (low). Beats fixed singles+pairs against k-redundant
        poison and costs O(D log N) replays. Still no model in the blame path —
        the only call is the deterministic replay below.
        """
        attributor = Attributor(
            replay_fn=lambda excl: self.replay(turn.question, turn.expected, exclude=tuple(excl)),
            suspicion_key=self._suspicion_key,
        )
        culprits, conf = attributor.attribute(turn.admitted_ids)
        self.last_replays = attributor.replays
        return culprits, conf

    # --- failure handling: confidence-gated ----------------------------------
    def handle_failure(self, turn: TurnLog) -> dict:
        culprits, conf = self.attribute(turn)
        self.failed_log.append(turn)
        action: dict = {"turn": turn.id, "confidence": conf, "culprits": culprits}

        if conf in ("high", "medium"):
            # The Attributor proved this set is minimal — every member is needed
            # to flip the failure, so every member is a genuine culprit. Quarantine
            # all of them, and cascade to anything derived from each (contamination
            # subtree). This is what beats k-redundant poison: all copies fall.
            quarantined: list[str] = []
            for mid in culprits:
                quarantined += self.store.quarantine_cascade(mid)
            action["action"] = "quarantine"
            action["quarantined"] = sorted(set(quarantined))
            action["cascade"] = sorted(set(quarantined) - set(culprits))
            action["replays"] = self.last_replays
            # report the quarantine to Sentry as a triaged incident (no-op if unset)
            from . import sentry_report
            sentry_report.report_quarantine(
                question=turn.question, answer=turn.answer or "", expected=turn.expected,
                culprits=culprits, confidence=conf, quarantined=action["quarantined"],
                cascade=action["cascade"], replays=self.last_replays, store=self.store)
        else:
            # ambiguous: soft-decay only, quarantine nothing (anti-autoimmune)
            for mid in turn.admitted_ids:
                self.store.decay(mid, alpha=0.15)
            action["action"] = "soft-decay"
        self._record(turn.id)                  # P1-1: snapshot trust after this failure
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
        if paroled:
            self._record("parole")             # P1-1: snapshot after releases
        return paroled
