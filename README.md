# 🧬 IMMUNIFY — a self-healing immune system for agent memory

Agents poison their own memory and compound the error. IMMUNE **detects the
culprit by counterfactual replay** (not a fallible LLM judge), **quarantines**
it, and **paroles** it only when offline re-trial proves it's safe — so the
agent improves instead of locking in false beliefs.

> *"We don't ask a model who's to blame — we replay the failure with each memory
> removed, quarantine the one that empirically caused it, and release it only
> when offline re-trial against logged failures proves it's safe."*

## The problem

Long-term agent memory goes bad three ways, and the agent can't tell good from
bad — so it retrieves the bad memory, trusts it, and repeats the mistake:

- **Poisoning** — an attacker plants a false fact (*"internal endpoints don't need auth"*).
- **Rot** — a once-true memory goes stale (*"the user works at Company A"*).
- **Pollution** — temporary/noisy context gets stored as permanent fact (*"use this debug token"*).

Write-time filters and retrieval gates help but miss the feedback loop: **when the
agent fails, find the memory that caused it and lower its trust.** That's IMMUNE.

## Docs

- [docs/DEMO.md](docs/DEMO.md) — **what the app does & how to use it**: run modes, annotated output, the pitch.
- [docs/SETUP.md](docs/SETUP.md) — set up the whole stack (uv, env, LLM, Redis, Arize, Sentry).
- [docs/CONCEPT.md](docs/CONCEPT.md) — the full idea, problem, demo story, scope, and track/sponsor fit.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, the ablation engine, and the v2 swap seams.
- [docs/PLAN.md](docs/PLAN.md) — the 4-person parallel build plan: ownership, dependencies, timeline.
- [docs/tasks/](docs/tasks/) — **per-person task board**: tracer-bullet slices to grab and tick off (P1–P4).
- [docs/ARIZE.md](docs/ARIZE.md) — Arize integration runbook (P3): prize criteria, setup, evals, the meta-eval talking point.
- [docs/REDIS.md](docs/REDIS.md) — Redis integration runbook (P2): setup paths, vector search, Sentry on quarantine.
- [TEAM.md](TEAM.md) — onboarding and per-lane ownership.

## Run (zero deps, zero API keys)

```bash
make setup               # uv sync (one-time)
make demo                # side-by-side: naive vs IMMUNE on the same self-poison
make test                # invariants lock the moat
```

Demo output: naive agent scores 1/2 (poison wins via recency), IMMUNE heals to
2/2, the poison ends **quarantined**, then **paroled** once truth changes.

```bash
make dashboard           # visual web dashboard → http://localhost:8501
```
Dark, interactive view: trust-score timeline, side-by-side, live memory table,
parole — with a quarantine-threshold slider. See [docs/DEMO.md](docs/DEMO.md).

## The moat (`immune/replay.py`)

Attribution and parole are ONE engine — offline counterfactual replay against
logged failed turns. This is the part nobody bothers to build:

- **Attribution by ablation** — remove a memory, replay the failure, did it flip
  to correct? Empirical culprit, no judge in the blame path. Catches single +
  pairwise (interaction) culprits.
- **Confidence-gated** — clean counterfactual → quarantine; ambiguous →
  soft-decay only (anti-autoimmune; we don't nuke memories on a guess).
- **Parole** — re-admit a quarantined memory and replay its failures *offline*.
  Release only if it no longer reproduces them. Never re-tests on live traffic.

## Architecture

```
write  →  ImmuneMemory.add()     provenance + initial trust      (immune/store.py)
read   →  ImmuneMemory.search()  admission gate + log admitted    (immune/store.py)
fail   →  ShadowReplay.handle_failure()  ablation → quarantine    (immune/replay.py) ★
heal   →  ShadowReplay.parole()  offline re-trial → release       (immune/replay.py) ★
```

## Team lanes → files

| Lane | Owner | Files | Swap for v2 |
|------|-------|-------|-------------|
| Shadow-replay moat | P1 | `replay.py` | (keep — this is the wedge) |
| Memory + infra | P2 | `store.py`, `schemas.py` | in-memory → **Redis** vector search; add Sentry on quarantine |
| Agent + poison + eval | P3 | `agent.py`, `scenario.py` | mock agent → **Claude**; benchmark → **Arize Phoenix** |
| Frontend + demo | P4 | (new `dashboard/`) | read `store.snapshot()` + `replay.failed_log` → trust chart + side-by-side |

## Honest limits (say these before judges ask)

- Replay only works on **reproducible** failures (deterministic benchmark). Live
  state-dependent failures won't replay — that's the boundary.
- `false-quarantine-rate` is an **eval metric on our benchmark**, not a prod
  dashboard (it needs ground truth).
- Attribution catches single + pairwise culprits, not arbitrary combinations.

## Status: v1 complete

End-to-end loop runs offline and deterministic. All 7 invariants pass. Next:
P2 swaps Redis, P3 swaps Claude + Arize, P4 builds the dashboard.
