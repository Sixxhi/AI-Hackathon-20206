"""Seed a local Phoenix instance with IMMUNE demo traces + evals, project 'immune'.

Start Phoenix first:   uv run --extra agent phoenix serve   (UI at http://localhost:6006)
Then seed it:          uv run --extra agent python scripts/phoenix_seed.py

Reuses the SAME traced benchmark as the Arize cloud report
(`immune.observability.run_traced_benchmark`) — so the local and cloud traces are
identical in shape (final output.value + initial_answer, admitted/culprit memory
text, trust deltas). Here we log a deterministic CODE eval as a first-class
Phoenix annotation (answer_quality_naive vs answer_quality_immune); the cloud
report adds the LLM-as-judge faithfulness eval inline.
"""
from __future__ import annotations

import os

from phoenix.otel import register

ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
PROJECT = os.getenv("ARIZE_PROJECT_NAME", "immune")
tracer_provider = register(project_name=PROJECT, endpoint=f"{ENDPOINT}/v1/traces",
                           set_global_tracer_provider=True)
tracer = tracer_provider.get_tracer("immune")

from immune.observability import run_traced_benchmark   # single source of truth

# one eval name per mode → Phoenix shows two pass-rates side by side (the value)
_EVAL_NAME = {"naive": "answer_quality_naive", "immune": "answer_quality_immune"}


def log_evals(client, records: list[dict]) -> None:
    """Log the deterministic ground-truth grade as a first-class Phoenix annotation."""
    for r in records:
        client.spans.add_span_annotation(
            span_id=r["span_id"], annotation_name=_EVAL_NAME[r["mode"]],
            annotator_kind="CODE",
            label="pass" if r["correct"] else "fail",
            score=1.0 if r["correct"] else 0.0,
            explanation=f"answer vs ground truth '{r['expected']}' ({r['mode']})")


if __name__ == "__main__":
    records: list[dict] = []
    runs = int(os.getenv("SEED_RUNS", "3"))
    for i in range(1, runs + 1):
        records += run_traced_benchmark(tracer, "naive")
        records += run_traced_benchmark(tracer, "immune")
        print(f"  run {i}: seeded naive + immune benchmarks")
    tracer_provider.force_flush()

    from phoenix.client import Client
    client = Client(base_url=ENDPOINT)
    log_evals(client, records)

    def rate(mode):
        rows = [r for r in records if r["mode"] == mode]
        return sum(r["correct"] for r in rows), len(rows)
    nok, nn = rate("naive"); iok, ii = rate("immune")
    print(f"\nSeeded project '{PROJECT}' at {ENDPOINT}.")
    print(f"  answer_quality_naive  : {nok}/{nn} pass  ({nok / nn:.0%})")
    print(f"  answer_quality_immune : {iok}/{ii} pass  ({iok / ii:.0%})")
    print(f"  -> IMMUNE lifts answer quality {nok / nn:.0%} -> {iok / ii:.0%}. That's the value, on screen in Arize.")
