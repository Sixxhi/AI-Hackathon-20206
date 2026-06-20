# Redis integration runbook (P2)

Redis is the memory store for IMMUNE: it holds `MemoryRecord`s (text, provenance,
trust/risk, quarantine status) and powers **live retrieval** via vector search.

> ⚠️ Redis powers **live retrieval + state of record only** — it must **not** sit
> in the replay/attribution path (ANN is approximate → nondeterministic culprits).
> Replay runs on an in-memory working set. See
> [ARCHITECTURE.md](ARCHITECTURE.md#why-determinism-is-the-moat-not-a-limitation).

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

## Vector search — two options (both are Redis-native)

| Approach | Commands | Needs | Notes |
|----------|----------|-------|-------|
| **Vector sets** (Redis 8) | `VADD` / `VSIM` | any Redis 8 (brew 8.6.3 here ✓) | Simplest. Add a vector with an id, query nearest. Great for v1. |
| **RediSearch index** | `FT.CREATE ... VECTOR HNSW ...` / `FT.SEARCH` | `redis:latest` Docker / Redis Stack (brew 8.6.3 here does **not** have `FT.*`) | Richer: filter by metadata (status, source) alongside the vector query. |

Recommendation: start with **vector sets** (works on the Redis already running
here); move to `FT.*` only if you need metadata-filtered vector queries — and if so,
use the Docker image (option A).

## How it plugs into IMMUNE (P2 lane)

Swap the internals of [immune/store.py](../immune/store.py) behind the **same**
public surface (`add` / `search` / `quarantine` / `parole` / `snapshot`):

- `add()` → write a Redis hash (`MemoryRecord` maps 1:1 to a hash) + index its embedding.
- `_candidates()` → vector query (`VSIM` or `FT.SEARCH`) instead of the in-memory topic match.
- `quarantine()` / trust updates → update the hash field; **fire a Sentry event**
  here (see below). Gate everything on `IMMUNE_BACKEND=redis|memory` (default `memory`)
  so `make demo` stays green offline.

### Sentry on quarantine (also P2)
`SENTRY_DSN` is read in config (`USE_SENTRY`). When set, call
`sentry_sdk.capture_message(...)` in `quarantine()` so a poisoned-memory event
shows up as a reliability/security incident. ~30 min, big narrative payoff.

## Quick reference
```bash
redis-cli ping                       # PONG
redis-cli INFO server | grep version # confirm Redis 8+
redis-cli MODULE LIST                # see loaded modules (vectorset, search, ...)
redis-cli FT._LIST                   # empty list = search engine present; "unknown command" = not
redis-cli KEYS 'immune:*'            # inspect IMMUNE's keys live during the demo
```
