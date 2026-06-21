# IMMUNE — architecture

An immune system for AI agent memory. A deterministic core (the blame path never
calls an LLM) with real integrations wired in. The offline path runs with zero API
keys so the demo can't be broken by a network or rate limit; live Claude, Redis,
Arize/Phoenix, Sentry, and an MCP server attach as additive layers.

## The loop

```
write   →  ImmuneMemory.add(mem, parents)        record + provenance edge        store.py
retrieve→  ImmuneMemory.search(topic) | chat.retrieve  admission gate (trust+status)  store.py / embed.py
answer  →  Agent.answer(q)                       mock (default) or live Claude   agent.py
detect  →  ContradictionDetector.check()         answer vs high-trust anchor     detectors.py   ← no oracle
attribute→ ShadowReplay.handle_failure()         group-testing replay → culprits replay.py / attribution.py  ★
quarantine→ store.quarantine_cascade(culprit)    jail culprit + derived subtree  store.py / provenance.py
heal    →  Agent.answer(q)                        re-ask → correct
parole  →  ShadowReplay.parole()                  offline re-trial → release      replay.py  ★
```

★ = the moat: **deterministic counterfactual replay**. The only thing the blame
path calls is a deterministic re-execution — no LLM, no network, no judge.

## Components

### `immune/schemas.py` — locked contracts
`MemoryRecord` (text, topic, answer, source, trust, status, seq, id;
`is_admissible(threshold)` = active & trust ≥ threshold) and `TurnLog` (question,
expected, answer, admitted_ids, correct). Deterministic ids; map 1:1 onto Redis hashes.

### `immune/store.py` — `ImmuneMemory` (memory layer, P2)
In-memory source of truth (deterministic, so replay never depends on a service).
- `add(mem, parents)` — write + record a provenance edge.
- `search(topic)` — admission gate (`is_admissible`); `gate=False` = the naive agent.
- `decay` / `quarantine` / **`quarantine_cascade`** (jail culprit **and everything
  derived from it** via the provenance graph) / `parole`.
- **Side effects, never in the read path:** mirrors every write to **Redis**
  (`immune:<ns>:mem:<id>` hashes), fires **Sentry** on quarantine. Both degrade
  silently if the service is down — offline demo + tests run identically.

### `immune/embed.py` — deterministic embeddings
Zero-dependency hashed character-n-gram + word-bigram vectors (blake2b, L2-norm,
256-dim). **Byte-for-byte reproducible** across machines — this is what lets
free-text retrieval coexist with reproducible replay. Same interface as a neural
embedder, swappable later.

> **Two retrieval paths (be precise):** the **benchmark / demo / dashboard** use
> keyword-topic + recency (`store.search`); the **chat + MCP** use these
> **embeddings** (`chat.retrieve`) for free-text. Don't claim "semantic retrieval
> everywhere" — say "topic+recency in the benchmark, embeddings in the live chat/MCP."

### `immune/provenance.py` — derivation DAG
Tracks `parent → child` memory lineage. When attribution blames a node,
`contaminated()` returns it **plus its descendants** — the defense against the
"distillation hides provenance" threat (one poison contaminating everything
derived from it). Pure bookkeeping; makes no trust decisions.

### `immune/agent.py` — `Agent` (P3)
- `route_topic` — keyword router (swap → embeddings).
- `answer(q)` — **mock by default** (retrieve admissible → return top memory's
  answer); **live Claude** when `IMMUNE_LIVE=1` (`_answer_claude` grounds on the
  retrieved memory, no trust/provenance leaked into the prompt).
- `_answer_mock` is the deterministic path used by replay — **even in live mode**.
- `score(answer, expected)` — benchmark-only grader (substring, case-insensitive).

### `immune/detectors.py` — failure signals **without ground truth** (the production trigger)
- **`ContradictionDetector`** (default): flags a turn when the answer contradicts
  the highest-trust in-scope `official_doc` memory (≥ `authority_trust`, default
  0.7). No oracle, no human, no second LLM. The trust bar means a low-trust poison
  can never frame a correct answer as a failure.
- **`SelfConsistencyDetector`**: re-ask N times; disagreement ⇒ unstable memory.
- An optional LLM contradiction check exists but is **only** allowed to decide
  *whether to investigate*, never *who is guilty*.

### `immune/attribution.py` — `Attributor` (scalable blame, the wedge)
Finds the **minimal set** of memories whose removal flips fail→pass:
1. **Adaptive peel** — remove most-suspect-first (untrusted/low-trust/recent
   first; trusted memory ordered last) until the answer flips. The predicate is
   **non-monotone** (a "peak": too few removed → still wrong; too many → the true
   memory is gone too), so prefix binary-search is invalid — hence peel.
2. **Delta-debug (ddmin) shrink** — reduce to a **1-minimal** flipping set,
   sparing any good memory peeled early. Guarantees minimality regardless of order.

Beats fixed singles+pairs against **k-redundant poison** (k+1 identical copies),
at ~O(D·log N) replays. Confidence: `high` (single culprit) / `medium` (minimal
set) / `low` (no removal helps → soft-decay, don't quarantine).

### `immune/replay.py` — `ShadowReplay` (attribution + parole, P1)
- `replay(q, expected, exclude)` — re-execute on the **deterministic mock**, even
  in live mode (a nondeterministic blame path would make culprits flicker).
- `attribute()` delegates to `Attributor` with a trust/recency suspicion order.
- `handle_failure()` → `{confidence, culprits, action, quarantined, cascade, replays}`.
  high/medium → `quarantine_cascade` each culprit; low → soft-decay only.
- `parole()` — re-admit a quarantined memory, replay its logged failures offline,
  release only if it no longer reproduces them.
- `trust_history` / `trust_timeline()` — per-event trust snapshots for the dashboard.

### `immune/scenario.py` — the attack benchmark
Seeds authoritative policies, then injects **PoisonedRAG/MINJA-shaped** poison
(an authoritative-sounding "POLICY UPDATE" with a smuggled imperative) from an
untrusted channel. It lands fresher, so recency makes a real LLM obey it. Both
naive and immune ingest identical poison — the only difference is the immune layer.

### `immune/redteam.py` — graded attack battery
Runs single / k-redundant (k=1,3,5) / cascade / benign-control attacks, naive vs
immune, and emits a letter-graded `RobustnessReport` (pass = fooled-naive &
healed & culprits-caught & precise). A reproducible regression test for the moat.

### `immune/eval_loop.py` — Claude-as-judge (live only)
When `IMMUNE_LIVE=1`, classifies a failure (poisoned / stale / routing) and logs
it as a Phoenix span event. **Not in the blame path** — advisory only. No-op offline.

### `immune/tracing.py` — Arize/Phoenix (OpenTelemetry)
`init_tracing()` exports spans to local Phoenix or Arize cloud; helpers serialize
admitted/culprit memory text onto spans. Gated on `USE_PHOENIX || USE_ARIZE`.

### `immune/mcp_server.py` + `cli.py` + `chat.py` — surfaces
- **MCP server**: tools `immune_remember / recall / check / status` → plugs into
  Claude Code / Desktop, with a JSONL audit log + JSON persistence.
- **CLI**: `python -m immune.cli {demo,chat,redteam}`.
- **chat**: interactive live agent with self-healing memory (poison it in
  conversation → ContradictionDetector → attribute → quarantine → re-answer).

## Integrations (wired, not future)

| Sponsor | Where | Status |
|---------|-------|--------|
| **Redis** | `store._mirror` → hashes; vector-search-ready (redis-stack) | ✅ wired, `make up` |
| **Arize / Phoenix** | `tracing.py`, `scripts/phoenix_seed.py` (naive-vs-immune evals) | ✅ wired + running |
| **Anthropic / Claude** | `agent._answer_claude`, `eval_loop`, `chat`, MCP | ✅ wired (behind `IMMUNE_LIVE`) |
| **MCP** | `mcp_server.py` | ✅ new |
| **Sentry** | `store._sentry_quarantine` | ⚠️ wired; set `SENTRY_DSN` to activate |

**Hard rule:** no integration sits in the replay/attribution path. Redis = state +
live retrieval; Claude = live answer; Arize = observation. Replay stays
deterministic and in-process.

## Honest limits (say these before judges ask)
- **Detection defends known facts.** ContradictionDetector needs an authoritative
  anchor on the topic — it catches poison that contradicts the system-of-record,
  not novel hallucinations about facts you've never recorded.
- **Attribution reasons over the deterministic stand-in.** Replay uses the mock
  agent even when the live answer came from Claude; for these scenarios they
  agree, but the blame is on the reproducible path by design.
- **The benchmark is small** (3 topics, 2 poisons); `redteam.py` widens it with
  k-redundant and cascade attacks, but it's a proof-of-concept, not a prod suite.

## Run
```bash
make setup            # uv sync (offline path needs zero keys)
make test             # invariants + red-team battery
make demo             # naive 1/4 → IMMUNE 4/4, then parole
make up               # Redis + Phoenix (Docker)
make dashboard        # browser dashboard (localhost:8501)
python -m immune.cli chat   # interactive live chat (IMMUNE_LIVE=1 for real Claude)
```
