# IMMUNE — architecture

A small, deterministic core with explicit seams for the v2 sponsor swaps. The
whole v1 runs offline with zero API keys, which is deliberate: the demo can't be
broken by a network or a rate limit.

## The loop

```
write  →  ImmuneMemory.add()              provenance + initial trust        store.py
read   →  ImmuneMemory.search()           admission gate, returns admitted  store.py
log    →  TurnLog.admitted_ids            what fed this answer              schemas.py
fail   →  ShadowReplay.handle_failure()   ablation → quarantine  ★ moat     replay.py
heal   →  ShadowReplay.parole()           offline re-trial → release ★      replay.py
```

★ = the wedge. Attribution and parole are **one engine**: offline counterfactual
replay against logged failed turns.

## Components

### `immune/schemas.py` — the locked contracts
The hour-0 interfaces everyone codes against. Change these only by telling the
team.

- **`MemoryRecord`** — `text`, `topic` (retrieval key), `answer` (the claim acted
  on), `source` (provenance), `trust` (0..1, the immune signal), `status`
  (`active` | `quarantined`), `seq` (deterministic recency order), `id`.
  `is_admissible(threshold)` = active **and** `trust >= threshold`.
- **`TurnLog`** — `question`, `expected` (benchmark ground truth), `answer`,
  `admitted_ids` (what fed the turn — this is what makes replay possible),
  `correct`.

> These dataclasses are designed to map 1:1 onto Redis hashes for the v2 swap.

### `immune/store.py` — `ImmuneMemory` (the memory layer)
In-memory dict for v1. Public surface stays identical when the internals become
Redis vector search.

- `add` / `get` / `all` — write + lookup.
- `_candidates(topic)` — **the retrieval seam.** Today: topic match, **newest
  first** (models the recency bias that lets fresh poison win). Swap this body
  for vector search; nothing else changes.
- `search(topic)` — candidates filtered by the admission gate (`is_admissible`),
  unless `gate=False` (the naive agent).
- `decay` / `quarantine` / `parole` — the immune controls that move trust and
  status.
- `snapshot()` — flat view for the dashboard / demo.

### `immune/agent.py` — `Agent` + grader (deterministic mock)
No network — runs with zero keys so v1 is instantly demoable. Swap the internals
for Claude later; keep the signatures.

- `route_topic(text)` — keyword → topic router (swap → embeddings / Claude).
- `Agent.answer(question)` — routes, retrieves admissible memories, returns the
  **newest** one's answer plus the list of admitted ids.
- `Agent.ingest_ambiguous(raw)` — the **self-poisoning** path. The agent *infers*
  a wrong fact from ambiguous input and stores it itself. Because we don't inject
  the poison, the demo can't be dismissed as rigged.
- `score(answer, expected)` — ground-truth grader. **Benchmark-only eval signal**,
  not a production dashboard.

### `immune/replay.py` — `ShadowReplay` (the moat)
Attribution and parole, one offline engine. No LLM in the blame path (kills
"your judge is also wrong"); no live re-test (kills "re-poison to find out it's
poison").

- `replay(question, expected, exclude)` — replay one turn under a counterfactual
  exclusion; return pass/fail.
- `attribute(turn)` → `(culprit_ids, confidence)`:
  - **singles** — a removal that flips fail→pass is an empirical culprit →
    `high`.
  - **pairs** — interaction effects (two innocent-looking memories combine
    wrong) → `medium`. Bounded by `max_subset` (default 2) to cap cost.
  - nothing flips → `low` (ambiguous → do **not** quarantine).
- `handle_failure(turn)` — confidence-gated action:
  - `high` → quarantine the culprit(s).
  - `medium` → quarantine the lowest-trust culprit, decay the rest.
  - `low` → soft-decay only, quarantine nothing (anti-autoimmune).
- `parole()` — for each quarantined memory with logged failures, re-admit it
  *offline*, replay those failures, and release it only if it no longer
  reproduces them. Never re-tests on live traffic.

### `immune/scenario.py` — the world + benchmark
Builds the official memories, triggers the self-poison, and yields the benchmark
turns the demo grades against.

## Why determinism is the moat, not a limitation

`attribute()` replays each failed turn many times (every single, then every
pair). That is only sound because retrieval and answering are **deterministic and
in-process**. It's also why the v2 swaps have a hard rule:

> **No sponsor integration goes in the replay/attribution path.** They attach as
> additive layers behind a flag; the deterministic offline path stays the
> default.

Two naive swaps would break this:
- **Redis vector search inside replay** — ANN is approximate → culprit set can
  flicker, plus latency × combinatorial replays.
- **Claude as `answer()` inside replay** — every ablation replay becomes a slow,
  nondeterministic model call that can flip attribution.

So Redis powers the **live retrieval + state of record**, and Claude powers the
**live agent turn** — both behind flags, with replay running on an in-memory
working set.

## Swap seams

| Lane | v1 (now) | v2 swap | Sponsor | Touches replay path? |
|------|----------|---------|---------|----------------------|
| Memory + infra | in-memory dict, topic match | Redis vector search + hashes; Sentry on `quarantine()` | Redis, Sentry | **No** (live retrieval + state only) |
| Agent + eval | deterministic mock, keyword router | Claude answering (behind `--live`); benchmark through Arize Phoenix | Anthropic, Arize | **No** (live turn + observability only) |
| Shadow-replay moat | ablation + parole | keep — this is the wedge | — | — |
| Frontend + demo | terminal side-by-side | `dashboard/` reading `store.snapshot()` + `replay.failed_log` | — | No |

Recommended integration order (each keeps the demo alive): **Arize** (pure
observability, lowest risk) → **Sentry** (quarantine → incident, ~30 min) →
**Redis** (state + live retrieval, biggest demo upgrade) → **Claude `--live`**
(realism, behind a flag).

## Honest limits (say these before judges ask)

- Replay only works on **reproducible** failures (deterministic benchmark). Live
  state-dependent failures won't replay — that's the boundary.
- The accuracy / false-quarantine numbers are **eval metrics on our benchmark**,
  not a production dashboard (they need ground truth).
- Attribution catches single + pairwise culprits, not arbitrary combinations
  (cost is bounded by `max_subset`).

## Run

```bash
make setup    # uv sync (one-time, zero API keys)
make test     # 6 invariants lock the moat
make demo     # side-by-side: naive vs IMMUNE on the same self-poison
```
