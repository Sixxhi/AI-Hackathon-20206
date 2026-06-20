# Setup — get everything running

One place to set up the whole stack. v1 runs with **zero** of the integrations
(pure mock, offline); add each only when your lane needs it.

## 0. Prerequisites
- **uv** (Python package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **git**, and access to the repo (`git@github.com:Sixxhi/AI-Hackathon-20206.git`)
- **Docker** — only if you want the Redis container (optional; see step 4)

## 1. Clone + base setup (everyone, 2 minutes)
```bash
git clone git@github.com:Sixxhi/AI-Hackathon-20206.git
cd AI-Hackathon-20206
git checkout immune-v1
make setup                 # uv sync — identical deps for everyone (uv.lock)
make test                  # 6 invariants -> all pass
make demo                  # side-by-side naive vs IMMUNE (offline, deterministic)
```
If `make demo` is green, you're ready. Everything below is additive.

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
Already running locally on this machine (brew Redis 8). Teammates: pick one path
(Docker / brew / cloud) in **[REDIS.md](REDIS.md)**. Quick version:
```bash
docker run -d --name my-redis -p 6379:6379 redis:latest    # OR: brew services start redis
make lane-infra            # installs redis-py + sentry-sdk
uv run --extra infra python -c "import redis,os; print(redis.from_url(os.getenv('REDIS_URL')).ping())"
```

## 5. Arize (P3) — tracing + evals
Already set up + verified on this machine (project `immune` is live). Full runbook,
including the `ax` CLI auth and the Arize Skills for coding agents:
**[ARIZE.md](ARIZE.md)**. Quick verify:
```bash
uv run --extra agent scripts/arize_smoketest.py   # sends a test trace
ax projects list                                  # 'immune' should appear
```

## 6. Sentry (P2) — quarantine alerts
Set `SENTRY_DSN` in `.env`; `USE_SENTRY` flips on. Wire `sentry_sdk.capture_message`
into `store.quarantine()`. See [REDIS.md](REDIS.md#sentry-on-quarantine-also-p2).

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
