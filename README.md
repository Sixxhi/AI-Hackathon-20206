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

- [docs/FIREWALL.md](docs/FIREWALL.md) — **the headline demo**: Claude agent + Redis memory firewall, run modes, sponsor map, the pitch script.
- [docs/DEMO.md](docs/DEMO.md) — the side-by-side naive-vs-IMMUNE demo: run modes, annotated output.
- [docs/SETUP.md](docs/SETUP.md) — set up the whole stack (uv, env, LLM, Redis, Arize, Sentry).
- [docs/CONCEPT.md](docs/CONCEPT.md) — the full idea, problem, demo story, scope, and track/sponsor fit.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, the ablation engine, and the v2 swap seams.
- [docs/PLAN.md](docs/PLAN.md) — the 4-person parallel build plan: ownership, dependencies, timeline.
- [docs/tasks/](docs/tasks/) — **per-person task board**: tracer-bullet slices to grab and tick off (P1–P4).
- [docs/ARIZE.md](docs/ARIZE.md) — Arize integration runbook (P3): prize criteria, setup, evals, the meta-eval talking point.
- [docs/MCP.md](docs/MCP.md) — plug IMMUNE into Claude Code as an MCP server (`claude mcp add` + scripted demo).
- [docs/REDIS.md](docs/REDIS.md) — Redis integration runbook (P2): setup paths, vector search, Sentry on quarantine.
- [TEAM.md](TEAM.md) — onboarding and per-lane ownership.

## The headline demo — a memory firewall (Claude + Redis)

IMMUNE is a **firewall for agent memory**: it sits on the read/write path,
provenance-tags every write, and quarantines poison so it can't be retrieved.
The flagship demo runs a **real Claude agent** whose memory is **Redis vector
search**, gets it poisoned, and heals it — live.

```bash
make demo-firewall            # live: real Claude + Redis; needs ANTHROPIC_API_KEY + Redis (make up)
make demo-firewall-offline    # deterministic, zero network — the can't-fail backup
```
You watch the Redis index reject the attack: **3 active → 4 (poison RETRIEVABLE)
→ 3 (poison not served)** the instant the culprit is quarantined; a Sentry
incident fires on quarantine. Full runbook + pitch: [docs/FIREWALL.md](docs/FIREWALL.md).

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

**Redis** (real vector search — RediSearch KNN drives recall; quarantine enforced
at the index via `@status:{active}`; `make up`) · **Anthropic/Claude** (live agent
behind `IMMUNE_LIVE`) · **Arize/Phoenix** (traces + naive-vs-immune evals) ·
**Sentry** (quarantine → triaged incident; set `SENTRY_DSN`) · **MCP**
(`immune/mcp_server.py` → Claude Code/Desktop) · **LangGraph** (secondary —
`ImmuneStore` is a drop-in `BaseStore`, `immune/langgraph_store.py`). The
replay/attribution moat stays in-memory and deterministic — no integration sits
in the blame path.

## Honest limits (say these before judges ask)

- **Detection defends known facts** — contradiction needs an authoritative anchor;
  it catches poison vs the system-of-record, not novel hallucinations.
- **Attribution reasons over the deterministic stand-in** (the mock), even when the
  live answer came from Claude — blame stays on the reproducible path by design.
- The benchmark is small (3 topics); `redteam.py` widens it (k-redundant, cascade).

## Status

End-to-end loop runs offline + deterministic; **44 tests pass** (incl. the
red-team battery, the LangGraph `BaseStore` drop-in, and Redis-gated vector
search). The headline demo (`make demo-firewall`) runs a real Claude agent on
Redis vector memory and self-heals live. Redis vector search, Arize/Phoenix,
Claude (live), MCP, and Sentry are wired; Sentry needs a DSN. Browser dashboard +
terminal chat both live.
