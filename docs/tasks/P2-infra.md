# P2 — Memory + infra (Redis + Sentry)

**Owns:** [`immune/store.py`](../../immune/store.py),
[`immune/schemas.py`](../../immune/schemas.py).
Swap the store internals to Redis **behind the same public surface**
(`add/get/all/search/quarantine/parole/snapshot`). Setup: [../REDIS.md](../REDIS.md).

> ⚠️ Redis = **live retrieval + state of record only**. Replay runs on an
> in-memory working set. Never put a Redis vector query in the attribution path.

---

### P2-1 · 🔴 must · ~30 min
## Backend flag + factory (no behavior change yet)
Plumb the switch first so everything after is additive.

**Steps**
- Read `IMMUNE_BACKEND` (default `memory`) in [config.py](../../immune/config.py).
- Add a `make_store()` factory (or `ImmuneMemory.create(...)`) that returns the
  in-memory impl today. Demo/replay call the factory.

**Done when** `IMMUNE_BACKEND=memory make demo` is identical to now. `make test` green.

---

### P2-2 · 🔴 must · ~1.5 h · dep: P2-1
## `RedisMemory` — write/read records
Implement `add/get/all/snapshot/quarantine/parole` against Redis hashes (a
`MemoryRecord` maps 1:1 to a hash; key e.g. `immune:mem:<id>`).

**Steps**
- New class same surface as `ImmuneMemory`; factory returns it when
  `IMMUNE_BACKEND=redis`.
- Store/load all `MemoryRecord` fields; keep a topic→ids index set for retrieval.
- Use `REDIS_URL` from config (`make lane-infra` installs `redis-py`).

**Done when** `IMMUNE_BACKEND=redis make demo` runs green and
`redis-cli KEYS 'immune:*'` shows the memories with their trust scores.

---

### P2-3 · 🔴 must · ~45 min · dep: P2-2
## Retrieval in Redis (topic-match first)
Reproduce `_candidates()` (newest-first topic match + admission gate) reading from
Redis. Keep it deterministic — this is the safe first slice before vectors.

**Done when** the Redis-backed demo attributes + quarantines exactly like the
in-memory one (same culprit, same accuracy).

---

### P2-4 · 🟡 should · ~1.5 h · dep: P2-3
## Vector search via RedisVL (the Redis headline + prize criterion)
Upgrade retrieval to vector search using **RedisVL** (a prize-qualifying tool —
makes "Redis beyond caching" obvious). Needs a Redis with the query engine:
`redis:latest` Docker or Redis Cloud (not the brew 8.6.3 here).

**Steps**
- `pip install redisvl` (add to the `infra` extra).
- Add an `embedding` field to `MemoryRecord` (additive — announce the schema change).
- Define a RedisVL `SearchIndex` (fields: text, topic, source, trust, status,
  embedding[VECTOR]); `index.load()` on add; `VectorQuery` on search, then apply
  the admission gate. Embeddings: a deterministic stub is fine for the demo.
- **Load the working set into memory for replay** — never query inside `replay()`.
- See [../REDIS.md](../REDIS.md#vector-search--use-redisvl-the-prize-qualifying-path).

**Done when** retrieval uses RedisVL vector similarity for the live turn; demo
still green; the index is visible via `redis-cli FT._LIST`.

> Quick win for the "beyond caching" criterion: also run
> `npx skills add redis/agent-skills` so Claude Code writes idiomatic Redis.

---

### P2-5 · 🟡 should · ~30 min · dep: P2-1
## Sentry on quarantine
Turn a quarantine into an observable incident.

**Steps**
- Init `sentry_sdk` when `USE_SENTRY` (config reads `SENTRY_DSN`).
- In `quarantine()`, `capture_message(f"IMMUNE quarantined {mem_id} ...", level="warning")`
  with culprit/confidence context.

**Done when** quarantining in the demo creates a Sentry event; with no DSN set,
nothing fires and the demo is unchanged.

---

### P2-6 · 🟢 nice · ~20 min
## `make redis-peek`
A target that prints `immune:*` keys + trust scores from `redis-cli` — a great
live visual for the pitch.

**Done when** `make redis-peek` shows the poison's trust crashing in Redis.
