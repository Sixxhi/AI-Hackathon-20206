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

## Vector search — use RedisVL (the prize-qualifying path)

**RedisVL** (Redis Vector Library) is a listed *qualified tool* and the cleanest
Python path — use it so the prize criterion "Using Redis beyond caching" is
obvious. `pip install redisvl` (add to the `infra` extra).

```python
from redisvl.index import SearchIndex
from redisvl.query import VectorQuery
# define a schema (fields: text, topic, source, trust, status, embedding[VECTOR])
# index.create(); index.load(records); index.query(VectorQuery(vector=..., ...))
```
RedisVL uses the `FT.*` search engine under the hood, so it needs a Redis with the
**query engine**: `redis:latest` Docker (option A) or **Redis Cloud** — *not* the
brew 8.6.3 here (it has vector sets but no `FT.*`). Easiest: run option A's
container, or use the Cloud DB you create with the credits.

Lower-level alternatives if you don't want RedisVL:

| Approach | Commands | Needs |
|----------|----------|-------|
| **Vector sets** | `VADD` / `VSIM` | any Redis 8 (brew 8.6.3 ✓) — works *now*, but RedisVL reads better in the demo |
| **Raw RediSearch** | `FT.CREATE ... VECTOR HNSW` / `FT.SEARCH` | `redis:latest` / Cloud |

Either way: **load the working set into memory for replay** — never run a vector
query inside `replay()`.

## Redis AI tools worth leveraging (for the "beyond caching" criterion)

The judges explicitly reward using Redis's AI tooling. Options, easiest first:

- **`npx skills add redis/agent-skills`** — Redis's Agent Skill so Claude Code
  writes Redis code the expert way (same idea as the Arize skills). Fastest start.
- **RedisVL** — vector DB / semantic cache / LLM memory / semantic routing (above).
- **Agent Memory Server** — RESTful + MCP server for dual-tiered agent memory
  (session "working" + persistent "long-term").
  https://github.com/redis-developer/agent-memory-server — a strong "agent memory"
  story, but it's a separate service with its own memory model; only adopt as the
  substrate if it fits the deterministic-replay design (evaluate before committing).
- **LangCache** — Redis's semantic cache-as-a-service. Cache answers for
  semantically-similar questions to cut LLM calls (pairs well with the live agent
  + Arize evals; counts as "beyond caching" AI tooling).
- **Redis AI Incubator** — experimental tools incl. `claude-mcp-redis`, `adk-redis`.
  https://redis.io/ai-incubator/
- **redis-ai-resources / python-recipes** — Redis's official cookbook of runnable
  Jupyter recipes: vector search, RAG, semantic cache, agent memory, RedisVL.
  Best copy-paste source for P2.
  https://github.com/redis-developer/redis-ai-resources/tree/main/python-recipes

## Workshop reference — "Hack Buddy"
Redis's hands-on workshop repo (the one from the session):
**https://github.com/justin-cechmanek/berkeley-ai-hackathon** — and the notebook is
vendored locally at [reference/redis_ai_workshop.ipynb](reference/redis_ai_workshop.ipynb).

The notebook builds a knowledge-grounded chatbot
across the three features we care about — copy the patterns, swap their chatbot
for IMMUNE:

| Workshop part | Library | Steal it for |
|---------------|---------|--------------|
| **Vector search** | RedisVL | P2 retrieval — index memories, query by meaning ([P2-4](tasks/P2-infra.md)) |
| **Semantic cache** | LangCache | optional: cache live-agent / eval-LLM answers |
| **Agent memory** | Agent Memory SDK | the persistent-memory substrate option |

Setup (their flow): free 30 MB DB at redis.io/try-free (use code `CALHACKER2026`
for $50) → enable LangCache + Agent Memory in the Cloud console → `.env` →
`pip install -r requirements.txt`. Runs in Jupyter or Colab. (Their notebook uses
OpenAI; we'd point it at our swappable provider — see [config.py](../immune/config.py).)

**Vendored locally:** the notebook
[reference/redis_ai_workshop.ipynb](reference/redis_ai_workshop.ipynb), the slide
deck [reference/redis_workshop_slides.pdf](reference/redis_workshop_slides.pdf)
(step-by-step Cloud/LangCache/Agent-Memory setup screenshots), and their env
template [reference/redis_workshop.env.example](reference/redis_workshop.env.example).

### Cloud service setup (from the deck)
- **Redis DB:** redis.io/try-free → **Databases → New Database → "Try 30 MB for
  Free"** under Essentials → name, version 8.4, any vendor/region → **Create
  database** → **Connect** for the connection snippet + username/password.
- **LangCache:** left nav → **LangCache** → accept preview terms → **Quick create**
  → copy the API key (**shown once!**).
- **Agent Memory:** left nav → **Agent Memory** → **Quick create**.

### Their env vars (note: split host/port, not a single URL)
The workshop uses discrete vars rather than our `REDIS_URL`. Both work with
redis-py / RedisVL — if you adopt LangCache/Agent Memory, add these to `.env`:
```
REDIS_HOST=...  REDIS_PORT=...  REDIS_USER=default  REDIS_PASSWORD=...
LANGCACHE_URL=...  LANGCACHE_CACHE_ID=...  LANGCACHE_API_KEY=lc1_...
AGENT_MEMORY_ENDPOINT=...  AGENT_MEMORY_STORE_ID=...  AGENT_MEMORY_API_KEY=mem1_...
```
(IMMUNE's [config.py](../immune/config.py) reads `REDIS_URL`; either compose it
from host/port/password or add these vars if a lane needs the managed services.)

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
