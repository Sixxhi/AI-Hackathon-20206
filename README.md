# 🧬 IMMUNE — a self-healing immune system for agent memory

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
- [docs/MCP.md](docs/MCP.md) — plug IMMUNE into Claude Code as an MCP server (`claude mcp add` + scripted demo).
- [docs/REDIS.md](docs/REDIS.md) — Redis integration runbook (P2): setup paths, vector search, Sentry on quarantine.
- [TEAM.md](TEAM.md) — onboarding and per-lane ownership.

## Run (zero deps, zero API keys)

```bash
make setup               # uv sync (one-time)
make demo                # side-by-side: naive vs IMMUNE on the same self-poison
make test                # invariants lock the moat
```

Demo output: naive agent scores 1/4 (injected poison wins via recency), IMMUNE
heals to 4/4, the poison ends **quarantined**, then **paroled** once truth
changes. Runs identically with real Claude (`IMMUNE_LIVE=1`).

```bash
make dashboard           # visual web dashboard → http://localhost:8501
```
Dark, interactive view: trust-score timeline, side-by-side, live memory table,
parole — with a quarantine-threshold slider. See [docs/DEMO.md](docs/DEMO.md).

## The moat (`immune/replay.py` + `immune/attribution.py`)

The blame path is **deterministic counterfactual replay** — no LLM, no judge:

- **Attribution by group testing** — find the **minimal set** of memories whose
  removal flips the failure to correct: adaptive peel (most-suspect-first) + a
  delta-debug shrink to a 1-minimal set. Beats fixed singles/pairs against
  **k-redundant poison**, at ~O(D·log N) replays.
- **Detection without an oracle** (`detectors.py`) — a bad answer is caught by
  **contradiction with a higher-trust memory**, so no ground truth is needed in
  production.
- **Quarantine + provenance cascade** — jail the culprit and everything derived
  from it (`provenance.py`); ambiguous cases soft-decay only (anti-autoimmune).
- **Parole** — re-admit offline, replay logged failures, release only if safe.

## Architecture

```
write   →  store.add(mem, parents)           record + provenance edge      store.py
retrieve→  store.search(topic)               admission gate (trust+status) store.py / embed.py
answer  →  Agent.answer(q)                   mock (default) | live Claude  agent.py
detect  →  ContradictionDetector.check()     answer vs trusted anchor      detectors.py
attribute→ ShadowReplay.handle_failure()     group-testing replay          replay.py / attribution.py ★
quarantine→ store.quarantine_cascade()       culprit + derived subtree     store.py / provenance.py
parole  →  ShadowReplay.parole()             offline re-trial → release    replay.py ★
```
Full detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Integrations (wired)

**Redis** (memory mirror, `make up`) · **Arize/Phoenix** (traces + naive-vs-immune
evals) · **Anthropic/Claude** (live agent + judge, behind `IMMUNE_LIVE`) · **MCP**
(`immune/mcp_server.py` → Claude Code/Desktop) · **Sentry** (quarantine alerts;
set `SENTRY_DSN`). No integration sits in the replay/attribution path.

## Honest limits (say these before judges ask)

- **Detection defends known facts** — contradiction needs an authoritative anchor;
  it catches poison vs the system-of-record, not novel hallucinations.
- **Attribution reasons over the deterministic stand-in** (the mock), even when the
  live answer came from Claude — blame stays on the reproducible path by design.
- The benchmark is small (3 topics); `redteam.py` widens it (k-redundant, cascade).

## Status

End-to-end loop runs offline + deterministic; **20 tests pass** (incl. the
red-team battery). Redis, Arize/Phoenix, Claude (live), and an MCP server are
wired; Sentry needs a DSN. Browser dashboard + terminal chat both live.
