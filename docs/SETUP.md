# Setup — get everything running

One place to set up the whole stack. v1 runs with **zero** of the integrations
(pure mock, offline); add each only when your lane needs it.

## 0. Prerequisites
- **uv** (Python package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **git**, and access to the repo (`git@github.com:Sixxhi/AI-Hackathon-20206.git`)
- **Docker** — for the Redis + Phoenix containers (`make up`). Optional: the
  offline demo runs green without them.

## 1. Pull-to-run (everyone — full stack in ~4 commands)
```bash
git clone git@github.com:Sixxhi/AI-Hackathon-20206.git   # or: git pull
cd AI-Hackathon-20206 && git checkout immune-v1
make setup-all             # uv sync --all-extras — every lane's deps from uv.lock
cp .env.example .env       # local Redis/Phoenix endpoints prefilled; add keys later
make up                    # start redis (:6379) + phoenix (:6006) via docker compose
make test                  # 7 invariants -> all pass
make demo                  # side-by-side naive vs IMMUNE
```
If `make demo` is green, you're ready. **`make up` is optional** — without it,
`USE_REDIS`/`USE_PHOENIX` simply stay off and the offline demo still runs green
(the integrations degrade gracefully). Add API keys to `.env` when your lane
needs them (steps 3 & 6). The base path (no Docker, no keys) is just
`make setup && make test && make demo`.

## 2. Environment file
```bash
cp .env.example .env       # .env is gitignored — never commit real keys
```
Fill only the keys your lane needs. All keys/models/endpoints are read once in
[immune/config.py](../immune/config.py); feature flags (`USE_LLM`, `USE_REDIS`,
`USE_SENTRY`, `USE_ARIZE`) flip on automatically when the relevant vars are set.

| Variable | For | Where to get it |
|----------|-----|-----------------|
| `IMMUNE_LLM_PROVIDER` | P3 | `anthropic` (default) / `openai` / `google` |
| `ANTHROPIC_API_KEY` | P3 | console.anthropic.com (or the matching provider key) |
| `IMMUNE_AGENT_MODEL` / `IMMUNE_JUDGE_MODEL` | P3 | model ids — swap freely (defaults: Haiku 4.5 / Sonnet 4.6) |
| `ARIZE_API_KEY` / `ARIZE_SPACE_ID` | P3 | Arize UI, or `ax spaces list` — see [ARIZE.md](ARIZE.md) |
| `REDIS_URL` | P2 | local `redis://localhost:6379/0` or cloud — see [REDIS.md](REDIS.md) |
| `SENTRY_DSN` | P2 | sentry.io project settings |

## 3. LLM (P3) — provider, model, and key are all swappable
```bash
# defaults to Anthropic; set the key for whichever provider you choose
ANTHROPIC_API_KEY=...      # in .env
```
Verify:
```bash
uv run --extra agent python -c "from immune import config as c; print(c.LLM_PROVIDER, c.AGENT_MODEL, 'key set:', bool(c.LLM_API_KEY))"
```
Switch provider/model with **no code change** — just edit `IMMUNE_LLM_PROVIDER` /
`IMMUNE_AGENT_MODEL` / `IMMUNE_JUDGE_MODEL` in `.env`. Details:
config knobs in [immune/config.py](../immune/config.py).

## 4. Redis (P2) — memory store + vector search
`make up` starts redis-stack in Docker (see [docker-compose.yml](../docker-compose.yml));
data persists in a named volume across restarts. `store.py` mirrors every memory
mutation into `immune:<ns>:mem:<id>` hashes. Verify:
```bash
make up                    # or: docker compose up -d redis
uv run python -c "import redis,os; from dotenv import load_dotenv; load_dotenv(); print(redis.from_url(os.getenv('REDIS_URL')).ping())"
docker exec immune-redis redis-cli KEYS 'immune:*'
```
Other paths (brew / cloud) and the vector-search roadmap: **[REDIS.md](REDIS.md)**.

## 5. Arize / Phoenix (P3) — tracing + evals
`make up` also starts **local Phoenix** on http://localhost:6006 (zero network,
demo-safe). `init_tracing()` (in [immune/tracing.py](../immune/tracing.py)) sends
spans there automatically once `PHOENIX_COLLECTOR_ENDPOINT` is set (it is, in
`.env.example`). For **Arize cloud** (post-hackathon) set `ARIZE_API_KEY` /
`ARIZE_SPACE_ID` — full runbook + `ax` CLI in **[ARIZE.md](ARIZE.md)**. Verify:
```bash
make up                                   # phoenix UI -> :6006
uv run demo.py && open http://localhost:6006   # traces appear after a run
```

## 6. Sentry (P2) — quarantine alerts
**Wired** — `store.quarantine()` fires `sentry_sdk.capture_message` (gated on
`USE_SENTRY`). Just add your DSN:
```bash
# in .env:
SENTRY_DSN=https://...@...ingest.sentry.io/...
uv run demo.py            # quarantine events land in your Sentry project
```
With no DSN, `USE_SENTRY` stays off and the call is a no-op — demo unaffected.

## Lane cheat-sheet
- `make setup` — base (everyone)
- `make lane-infra` — P2: redis + sentry
- `make lane-agent` — P3: anthropic + arize + phoenix
- `make setup-all` — everything

## Golden rules
1. **`make demo` stays green** at every merge — integrations hide behind flags.
2. **No integration in the replay path** — keep attribution deterministic.
3. **Never commit `.env`** — it's gitignored; share keys out-of-band.

See [PLAN.md](PLAN.md) for who builds what, and [TEAM.md](../TEAM.md) for branch flow.
