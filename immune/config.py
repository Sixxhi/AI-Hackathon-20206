"""Central config — read once from env so lanes integrate without hardcoding.

v1 ignores all of this (mock agent, in-memory store). P2/P3 read from here when
swapping in Redis / Claude so nothing is hardcoded across the codebase.
"""
from __future__ import annotations

import os

try:                                   # optional in v1
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# tunables
TRUST_THRESHOLD = _f("IMMUNE_TRUST_THRESHOLD", 0.3)

# --- LLM: provider, models, and keys are ALL swappable via env ---------------
# Pick a provider, set that provider's key, pick your models. No code changes.
LLM_PROVIDER = os.getenv("IMMUNE_LLM_PROVIDER", "anthropic").lower()

# Per-provider API keys (set the one matching LLM_PROVIDER).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

_PROVIDER_KEYS = {
    "anthropic": ANTHROPIC_API_KEY,
    "openai": OPENAI_API_KEY,
    "google": GOOGLE_API_KEY,
}


def llm_api_key(provider: str | None = None) -> str:
    """Resolve the API key for the active (or a given) provider."""
    return _PROVIDER_KEYS.get((provider or LLM_PROVIDER).lower(), "")


# Models — switch freely without touching code.
#   AGENT_MODEL = the agent-under-test (cheap/fast).
#   JUDGE_MODEL = the eval/failure-detector (bigger model -> more reliable grading).
AGENT_MODEL = os.getenv("IMMUNE_AGENT_MODEL", "claude-haiku-4-5-20251001")
JUDGE_MODEL = os.getenv("IMMUNE_JUDGE_MODEL", "claude-sonnet-4-6")
LLM_API_KEY = llm_api_key()

# integration endpoints (empty in v1)
REDIS_URL = os.getenv("REDIS_URL", "")
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "")

# Arize tracing / eval
ARIZE_API_KEY = os.getenv("ARIZE_API_KEY", "")
ARIZE_SPACE_ID = os.getenv("ARIZE_SPACE_ID", "")
ARIZE_PROJECT_NAME = os.getenv("ARIZE_PROJECT_NAME", "immune")

# feature flags — flip on as each lane lands its integration
USE_REDIS = bool(REDIS_URL)
USE_LLM = bool(LLM_API_KEY)              # provider-agnostic: any LLM configured
USE_CLAUDE = LLM_PROVIDER == "anthropic" and bool(ANTHROPIC_API_KEY)
USE_SENTRY = bool(SENTRY_DSN)
USE_ARIZE = bool(ARIZE_API_KEY and ARIZE_SPACE_ID)
