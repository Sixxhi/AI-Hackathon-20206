"""Tests are ALWAYS deterministic/offline, regardless of what .env says.

`.env` may set IMMUNE_LIVE=1 to make `demo`/`chat` call Claude. The invariant
tests must NOT depend on a network model — a flaky LLM answer would make them
non-reproducible. We force the flag OFF here, before `immune` is imported, so
config reads this value; python-dotenv's load_dotenv(override=False) then leaves
it alone.
"""
import os

os.environ["IMMUNE_LIVE"] = "0"

# Tests must never touch the network. `.env` may set SENTRY_DSN / REDIS_URL /
# ARIZE_* for live demos; neutralize them here BEFORE `immune` is imported so
# config sees empty values (USE_SENTRY/USE_REDIS/USE_ARIZE -> False) and
# load_dotenv(override=False) leaves these already-present keys alone. The Sentry
# integration is still unit-tested via an injected fake client in test_advanced.
for _k in ("SENTRY_DSN", "REDIS_URL", "ARIZE_API_KEY", "ARIZE_SPACE_ID",
           "PHOENIX_COLLECTOR_ENDPOINT"):
    os.environ[_k] = ""
