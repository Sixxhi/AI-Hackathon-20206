"""Delete the local Phoenix 'immune' project (all traces + evals).

Usage:
    uv run --extra agent python scripts/phoenix_clean.py
    make phoenix-clean

Then re-seed:  make phoenix-seed
"""
from __future__ import annotations

import os
import sys

ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
PROJECT = os.getenv("ARIZE_PROJECT_NAME", "immune")


def main() -> None:
    try:
        from phoenix.client import Client
    except ImportError:
        sys.exit("Install agent extras first:  uv sync --extra agent")

    client = Client(base_url=ENDPOINT)
    names = {p["name"] for p in client.projects.list()}
    if PROJECT not in names:
        print(f"No project '{PROJECT}' at {ENDPOINT} — nothing to clean.")
        return

    client.projects.delete(project_name=PROJECT)
    print(f"Deleted project '{PROJECT}' at {ENDPOINT}.")
    print("Re-seed fresh traces:  make phoenix-seed")


if __name__ == "__main__":
    main()
