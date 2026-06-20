# P1 — Shadow-replay moat

**Owns:** [`immune/replay.py`](../../immune/replay.py) · **Touch nothing else.**
Your engine is the wedge and it already works — your job is to harden it and feed
the dashboard. Read [../ARCHITECTURE.md](../ARCHITECTURE.md) first.

> ⚠️ Keep attribution **deterministic**. No LLM, no Redis, no network in the
> replay path — that property is the whole pitch.

---

### P1-1 · ✅ DONE · unblocks P4
## Emit `trust_history`
**Shipped:** `ShadowReplay.trust_history` (per-event snapshots) + `trust_timeline()`
→ `{mem_id: [(turn, trust), ...]}`. Baseline recorded at "start", then after each
failure and parole. P4 can plot it now. Covered by `test_trust_history_tracks_poison_drop`.

The dashboard needs trust-over-time to draw the money-shot chart. Snapshot trust
after every change so P4 can plot it.

**Steps**
- In `ShadowReplay.__init__`, add `self.trust_history: list[dict] = []`.
- After each `handle_failure(...)` and each `parole()`, append a record:
  `{"turn": <seq or label>, "snapshot": self.store.snapshot()}`
  (use the existing `store.snapshot()` — no cross-lane edit needed).
- Add `trust_timeline()` → `{mem_id: [(turn, trust), ...]}` for easy plotting.
- Record a **baseline** snapshot (turn 0) so the chart starts before any failure.

**Done when** `replay.trust_history` shows the poison's trust dropping across
turns, and `replay.trust_timeline()` returns a per-memory series. `make test` green.

---

### P1-2 · 🟡 should · ~30 min
## Expose a clean event stream
P4, Sentry (P2), and Arize (P3) all want a structured record of what happened.

**Steps**
- Add `self.events: list[dict] = []`; in `handle_failure`, append the action dict
  (already has `turn`, `confidence`, `culprits`, `action`) plus a `trust_delta`
  per culprit (trust before → after).
- Keep `handle_failure`'s return value unchanged (back-compat).

**Done when** `replay.events` is a list of dicts a UI can render with no parsing.

---

### P1-3 · 🟡 should · ~30 min
## Cost-guard the subset search
`attribute()` checks singles then pairs. With a large admitted set, pairs blow up
(O(n²) replays).

**Steps**
- If `len(admitted)` exceeds a threshold (config, e.g. 8), skip pairs (singles
  only) and `log` that the search was bounded — never silently truncate.
- Make `max_subset` / threshold read from config or `__init__` arg.

**Done when** attribution on a big admitted set stays fast; behavior on the demo
(small sets) is unchanged. `make test` green.

---

### P1-4 · 🟢 nice · ~30 min
## Attribution explanations
For the dashboard + Arize, add a human-readable reason per attribution
(e.g. `"removing mem_14 flipped turn_2 fail→pass"`). Include it in `events`.

**Done when** each event carries a one-line `explanation`.

---

### P1-5 · 🟢 nice · ~30 min
## Tests for the new surface
Add invariants to [`tests/test_immune.py`](../../tests/test_immune.py): trust_history
is monotonic-down for a quarantined memory; cost-guard caps replays; events shape
is stable.

**Done when** new tests pass and total count is reflected in the README badge line.
