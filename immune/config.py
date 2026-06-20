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

# integration endpoints (empty in v1)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "")
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "")

# feature flags — flip on as each lane lands its integration
USE_REDIS = bool(REDIS_URL)
USE_CLAUDE = bool(ANTHROPIC_API_KEY)
USE_SENTRY = bool(SENTRY_DSN)
