"""Tests are ALWAYS deterministic/offline, regardless of what .env says.

`.env` may set IMMUNE_LIVE=1 to make `demo`/`chat` call Claude. The invariant
tests must NOT depend on a network model — a flaky LLM answer would make them
non-reproducible. We force the flag OFF here, before `immune` is imported, so
config reads this value; python-dotenv's load_dotenv(override=False) then leaves
it alone.
"""
import os

os.environ["IMMUNE_LIVE"] = "0"
