"""Arize smoke test — verify creds and send one trace to AX.

Usage:
    uv run --extra agent scripts/arize_smoketest.py

Reads ARIZE_API_KEY / ARIZE_SPACE_ID (and optional ARIZE_PROJECT_NAME) from the
environment or a local .env. Sends a single parent span with a child span so the
"Listening for traces..." onboarding screen lights up and the project appears in
AX. This is just a connectivity check — real instrumentation lives in P3's lane.
"""
from __future__ import annotations

import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from arize.otel import register, Endpoint
from opentelemetry import trace


def main() -> None:
    api_key = os.environ.get("ARIZE_API_KEY")
    space_id = os.environ.get("ARIZE_SPACE_ID")
    project = os.environ.get("ARIZE_PROJECT_NAME", "immune")
    if not api_key or not space_id:
        raise SystemExit("Set ARIZE_API_KEY and ARIZE_SPACE_ID (e.g. in .env).")

    register(
        space_id=space_id,
        api_key=api_key,
        project_name=project,
        endpoint=Endpoint.ARIZE,
    )
    tracer = trace.get_tracer(__name__)

    # Mimic an IMMUNE turn: a parent "turn" span with a child "attribution" span.
    with tracer.start_as_current_span(
        "immune_turn",
        attributes={"input.value": "What's the refund window?"},
    ) as turn:
        turn.set_attribute("output.value", "30 days")
        turn.set_attribute("immune.correct", True)
        with tracer.start_as_current_span(
            "attribution",
            attributes={
                "immune.culprits": "['mem_14']",
                "immune.confidence": "high",
                "immune.action": "quarantine",
            },
        ):
            time.sleep(0.05)

    print(f"✓ Sent smoke-test trace to AX project '{project}'.")
    print("  Flushing spans (give it ~5s, then check the AX UI)...")
    # register() installs a BatchSpanProcessor; flush before the process exits.
    trace.get_tracer_provider().force_flush()
    time.sleep(2)
    print("  Done. Look for project 'immune' in your Arize space.")


if __name__ == "__main__":
    main()
