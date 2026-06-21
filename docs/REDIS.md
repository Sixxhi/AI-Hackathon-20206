# Redis integration runbook (P2)

> ✅ **Status: implemented.** Recall runs real RediSearch vector search
> (`FT.SEARCH … KNN`, FLAT/COSINE) in [`immune/redis_index.py`](../immune/redis_index.py);
> memories are mirrored with FLOAT32 embeddings and quarantine is enforced at the
> index (`@status:{active}`). See it live in [FIREWALL.md](FIREWALL.md) /
> `make demo-firewall`. The sections below are the original planning notes
> (RedisVL etc. were design options; the shipped path is raw `FT.*`).

Redis is the memory store for IMMUNE: it holds `MemoryRecord`s (text, provenance,
trust/risk, quarantine status) and powers **live retrieval** via vector search.

> ⚠️ Redis powers **live retrieval + state of record only** — it must **not** sit
> in the replay/attribution path (ANN is approximate → nondeterministic culprits).
> Replay runs on an in-memory working set. See
> [ARCHITECTURE.md](ARCHITECTURE.md#why-determinism-is-the-moat-not-a-limitation).

## Prize & how IMMUNE qualifies 🏆

**Best Use of Redis** — Mac Minis (one per team member) + 25k Redis Cloud credits +
backpacks. Worth aiming for, because IMMUNE fits the criteria almost too well.

**Qualify:** use any qualified Redis tool — **Redis Cloud, Redis OSS, RedisVL,
Agent Memory Server, Redis AI Incubator** — and show it **clearly in the demo and
the GitHub repo**. Built this weekend, no plagiarism.

**Judging criteria → our angle:**
1. **Using Redis *beyond caching*** (their #1) — agent memory, vector search,
   context retrieval. IMMUNE *is* an agent-memory system: memories + embeddings +
   trust/quarantine state, retrieved by vector search. Lead with this.
2. **Creativity / originality** — "immune system for agent memory" + counterfactual
   replay is a genuinely novel use of a memory store.
3. **Technical implementation** — correctness, architecture. The clean
   `store.py` swap-seam + `redis-cli`-visible trust scores show real engineering.

> Make it obvious on screen: show `redis-cli KEYS 'immune:*'` / the vector index,
> and say "Redis is our memory substrate" in the pitch.

## Credits + Cloud setup ($50, code `CALHACKER2026`)

For a shared/cloud store (also a clean demo backup):
1. **redis.io/login** → create account → **+ Database**
2. **Essentials tier** (best for the hack); pick size + cloud provider; **turn off
   High Availability** (saves credits)
3. Add credit code **`CALHACKER2026`** ($50) → **Confirm & Pay**
4. Copy the connection string into `.env` → `REDIS_URL=redis://default:<pw>@<host>:<port>/0`

**Workshop:** vector search + caching + agent memory — today **4:00–5:00 PM, 5th
Floor, Tilden Room**. Booth + Slack for setup help.

## Status on this machine ✅

A local Redis (Homebrew, **v8.6.3**) is already running on `localhost:6379` and is
verified working from the project: `PING` ok, `SET/GET` ok, and native vector
search (`VADD`/`VSIM`) ok. `.env` already has `REDIS_URL=redis://localhost:6379/0`.
Nothing more to do here — teammates use one of the three setups below.

## Setup — pick one (all expose `redis://localhost:6379`)

### A. Local Docker image (the Redis sponsor's recommended path)
```bash
docker pull redis:latest
docker run -d --name my-redis -p 6379:6379 redis:latest
```
`redis:latest` (Redis 8.8) includes **both** the `FT.*` search engine *and* vector
sets — the most capable option. Stop/remove with `docker stop my-redis && docker rm my-redis`.

> If port 6379 is already taken (e.g. a brew Redis like on this machine), either
> stop the other one, or map a different host port: `-p 6380:6379` and set
> `REDIS_URL=redis://localhost:6380/0`.

### B. Homebrew (already set up on this machine)
```bash
brew install redis
brew services start redis     # runs on 6379, survives reboots
redis-cli ping                # -> PONG
```

### C. Free cloud account — https://redis.io/try-free/
Create a database, copy its connection string into `.env`:
```
REDIS_URL=redis://default:<password>@<host>:<port>/0
```
Good for a shared store the whole team hits, or as a demo backup.

## Connect from the project
`REDIS_URL` is read in [immune/config.py](../immune/config.py) (`USE_REDIS` flips
true automatically when it's set). Verify anytime:
```bash
uv sync --extra infra      # or: make lane-infra  (installs redis-py + sentry-sdk)
uv run --extra infra python -c "import redis,os; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0')); print(r.ping())"
```

## Vector search — how it's wired (shipped)

Recall runs **raw RediSearch** (`FT.CREATE` FLAT/COSINE + `FT.SEARCH … KNN`) in
[`immune/redis_index.py`](../immune/redis_index.py); [`immune/store.py`](../immune/store.py)
mirrors each memory as a hash with a FLOAT32 `embedding` and exposes
`vector_candidates()`. Quarantine is enforced at the index via `@status:{active}`,
so a jailed memory can't be returned at all.

Needs a Redis with the **query engine** (`FT.*`): the brew **8.6.3** on this
machine has vector sets but *not* `FT.*` — use the `redis:latest` Docker (setup A)
or **Redis Cloud**. FLAT (not HNSW) is deliberate: exact cosine = deterministic
ranking. **Never run a vector query inside `replay()`** — replay uses the
in-memory working set so attribution stays reproducible.

> RedisVL / Agent Memory Server / LangCache were evaluated as design options but
> are **not** in the shipped path. Don't reach for them unless you're replacing
> `redis_index.py` wholesale.

## How it plugs into IMMUNE (implemented)

[`immune/store.py`](../immune/store.py) keeps the same public surface
(`add` / `search` / `quarantine` / `parole` / `snapshot`); `add()` mirrors to a
Redis hash + indexes the embedding, recall calls `vector_candidates()`
(`FT.SEARCH … KNN`), and `quarantine_cascade()` flips the `status` field so the
index stops serving it. Everything stays green offline (in-memory cosine) when
`REDIS_URL` is unset.

**Sentry on quarantine** — when `SENTRY_DSN` is set,
[`immune/sentry_report.py`](../immune/sentry_report.py) fires an incident on
quarantine with the replay trail. See [FIREWALL.md](FIREWALL.md) live.

## Quick reference
```bash
redis-cli ping                       # PONG
redis-cli INFO server | grep version # confirm Redis 8+
redis-cli MODULE LIST                # see loaded modules (vectorset, search, ...)
redis-cli FT._LIST                   # empty list = search engine present; "unknown command" = not
redis-cli KEYS 'immune:*'            # inspect IMMUNE's keys live during the demo
```
