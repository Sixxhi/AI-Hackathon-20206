# IMMUNE — 4-person parallel build plan

How four people build at once without blocking each other. Builds on the lanes in
[TEAM.md](../TEAM.md); read that first for setup.

## The core trick: interfaces are firewalls

v1 is fully deterministic and offline, and the contracts are locked in
[schemas.py](../immune/schemas.py). So **nobody waits for anybody** — each person
swaps an *implementation* behind a frozen interface while the mock keeps working.
You integrate by replacing internals, not by blocking on each other.

**Two rules that prevent ~90% of hackathon collisions:**

1. **Freeze the contracts after hour 1.** `MemoryRecord`, `TurnLog`,
   `ImmuneMemory.add/search/quarantine/parole/snapshot`,
   `ShadowReplay.replay/handle_failure`. Need a new field? Add it **additively**
   and announce in chat — never rename or remove.
2. **`make demo` stays green at every merge.** Every sponsor integration hides
   behind a flag / env var; with the flag off, the offline demo runs exactly as
   it does today.

## Ownership — no two people touch the same file

| Person | Lane | Owns only | Sponsor |
|--------|------|-----------|---------|
| **P1** | Moat | `immune/replay.py` | — |
| **P2** | Memory + infra | `immune/store.py`, `immune/schemas.py` | Redis, Sentry |
| **P3** | Agent + eval | `immune/agent.py`, `immune/scenario.py` | Anthropic/Claude, Arize |
| **P4** | Frontend + demo | new `dashboard/` (+ `demo.py`) | — |

The only shared file is `schemas.py` (P2 owns) — which is why it's frozen.

## The one real dependency: P1 → P4

P4's money-shot chart needs **trust-over-time data that doesn't exist yet.** This
is the only ordering constraint:

> **P1's first 60 minutes:** add a `trust_history` log (memory_id → list of
> `(turn, trust)`) and a stable event stream from `handle_failure`. The moment
> that's pushed, P4 is unblocked and can build the whole dashboard against the
> mock — no Redis, no Claude needed.

Everyone else starts immediately, in parallel.

## Per-person: first task → done

### P1 — Moat (`replay.py`) · *protect the wedge, feed the dashboard*
- **H0–1:** emit `trust_history` + clean event dicts (unblocks P4).
- Then: cost-guard the pair search (`max_subset`), expose `replay.failed_log` cleanly.
- **Done:** dashboard can read a trust timeline; `make test` green. Touch no other files.

### P2 — Redis + Sentry (`store.py`, `schemas.py`) · *swap behind the existing surface*
- Redis behind `ImmuneMemory` via `IMMUNE_BACKEND=redis|memory` (default `memory`).
  Vector search powers **live retrieval**; replay still runs on an in-memory
  working set.
- Sentry: fire on `quarantine()`, gated on `SENTRY_DSN` being set.
- ⚠️ **Redis must never sit in the replay path** — ANN is nondeterministic and
  would make attribution flicker. See [ARCHITECTURE.md](ARCHITECTURE.md#why-determinism-is-the-moat-not-a-limitation).
- **Done:** `IMMUNE_BACKEND=redis make demo` runs green; a quarantine shows up as
  a Sentry incident; `redis-cli` shows trust scores changing live.

### P3 — Claude + Arize (`agent.py`, `scenario.py`) · *realism behind a flag, observability for free*
- Claude as live `answer()`/`route_topic` behind `--live` / `ANTHROPIC_API_KEY`;
  the mock stays default.
- Arize Phoenix: instrument the benchmark — one span per turn + an attribution
  event (failure → culprit → trust drop). Run the **local Phoenix UI** so there's
  no network risk at judging. Full runbook + workshop code: [ARIZE.md](ARIZE.md).
- ⚠️ **Claude must never sit in the replay path** — keep the grader deterministic.
- **Done:** offline `make demo` unchanged; `--live` uses Claude; Phoenix UI shows
  the feedback loop.

### P4 — Dashboard (`dashboard/`) · *the money shot — start now against the mock*
- Build: trust-timeline chart (poison crashing, good memory climbing) +
  side-by-side naive/IMMUNE + a red **QUARANTINED** event. Reads
  `store.snapshot()`, `replay.failed_log`, and P1's `trust_history`.
- **Tech rec:** Streamlit (fastest path to a chart that screenshots well) or a
  tiny FastAPI + static HTML — whichever you know cold.
- **Done:** one command opens a page showing the trust line drop + quarantine.
  This *is* the pitch.

## Sponsors — scoped to what fits IMMUNE

Nothing is locked in yet; these are the four that map cleanly onto the
architecture (full reasoning in [CONCEPT.md](CONCEPT.md#track--sponsor-fit)):

| Sponsor | Lane | Why it fits | Risk |
|---------|------|-------------|------|
| **Arize** | P3 | Proves the failure→attribution→trust loop visually | Low (observability only) |
| **Sentry** | P2 | Quarantine = security incident; ~30 min | Low |
| **Redis** | P2 | The memory store; `redis-cli` trust crash is a great visual | Medium (keep out of replay path) |
| **Anthropic/Claude** | P3 | Live agent + Claude Code as build tool ("big swing") | Medium (keep out of replay path) |

**Integration order (each keeps the demo alive):** Arize → Sentry → Redis →
Claude. **Stretch only if ahead:** Browserbase as the *attack vector* (poison
enters via an untrusted webpage) — recorded for the pitch, not the live judging
run, because of network risk at hour 23.

> Discipline: every sponsor is an **additive layer behind a flag**. None sit in
> the replay/attribution path, which stays deterministic — so the offline demo
> can't be broken by a flaky network or rate limit.

## Timeline (~24h, judging Sun 1–3pm)

- **H0–1:** everyone runs `make setup/test/demo` green. P1 ships `trust_history`.
  Contracts frozen.
- **H1–12:** parallel build, each in a `lane/<name>` branch, merging into
  `immune-v1` often (small commits, direct merge — no PRs).
- **H12 — hard integration checkpoint:** all four merged; `make demo` green with
  every flag both ON and OFF. If a sponsor swap isn't talking, ship the offline
  version + dashboard and add sponsors as upside.
- **H12–20:** polish the dashboard, layer in whichever sponsors landed, rehearse
  the 90-second pitch off the dashboard.
- **H20+:** freeze. Record a backup screen capture of the demo so an hour-23
  network blip can't kill you.

## Branch flow

```bash
git checkout immune-v1
git checkout -b lane/<moat|infra|agent|frontend>
# work, commit small, merge back into immune-v1 frequently
```

Integrate into `immune-v1`. Keep `main` clean for the final submission tag.

## Golden rule

Whatever gets cut, the **before/after side-by-side stays** — it IS the pitch.
Keep `make demo` green at every merge.
