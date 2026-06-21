# P4 — Frontend + demo (the money shot)

**Owns:** new `dashboard/` (and you may extend
[`demo.py`](../../demo.py)). You build the thing judges actually look at. Start
**now** against the mock — you don't need Redis or Claude.

**Reads:** `store.snapshot()`, `replay.events`, and `replay.trust_history`
(from [P1-1](P1-moat.md#p1-1--emit-trust_history-)).

> Dependency: the trust chart needs **P1-1**. Until it lands, build everything
> else (layout, side-by-side, memory table) against `store.snapshot()`, which
> exists today.

**Tech:** Built with **Streamlit** (`make lane-frontend` / `make dashboard`).

> **✅ P4-1, P4-2, P4-3 shipped** in `dashboard/app.py` (dark theme, Altair trust
> timeline, side-by-side scorecards, highlighted memory table, parole verdict,
> threshold slider). Remaining: **P4-4** (richer failure-trace panel), **P4-5**
> (polish), **P4-6** (backup recording). Build on the existing app.

---

### P4-1 · 🔴 must · ~1 h
## Dashboard skeleton + memory table
Stand up the app; render the current memory state from `store.snapshot()` (id,
text, source, trust, status) with quarantined rows styled red.

**Done when** one command (e.g. `streamlit run dashboard/app.py`) opens a page
showing the live memory table.

---

### P4-2 · 🔴 must · ~1.5 h · dep: P1-1
## Trust-timeline chart (the money shot)
Plot trust per memory over turns from `replay.trust_history` — the poison line
crashing `0.62 → … → quarantined` while the good memory climbs.

**Done when** the chart clearly shows the poison dropping below threshold and
getting quarantined.

---

### P4-3 · 🔴 must · ~1 h
## Side-by-side + QUARANTINED event
Two columns: NAIVE (1/4, poison wins) vs IMMUNE (4/4, healed), and a red
**QUARANTINED** culprit banner when it fires. This IS the pitch.

**Done when** both runs render side-by-side with the accuracy numbers and the
quarantine event.

---

### P4-4 · 🟡 should · ~45 min
## Failure-trace panel
For each failed turn, show the attribution from `replay.events`: culprits,
confidence, action, trust delta.

**Done when** clicking/expanding a failed turn shows why it was blamed.

---

### P4-5 · 🟢 nice · ~45 min
## Polish for judging
Title, one-line tagline, IMMUNE branding, readable on a projector, looks good in
a screenshot. Add a "Parole" view if time (memory released after truth changes).

**Done when** it looks finished on a big screen.

---

### P4-6 · 🔴 must · ~20 min · do at H20+
## Record a backup capture
Screen-record the full demo (dashboard + side-by-side) so an hour-23 network blip
can't kill the judging run.

**Done when** there's an MP4/GIF of the working demo saved and shared.
