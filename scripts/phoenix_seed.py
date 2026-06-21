"""Seed a local Phoenix instance with IMMUNE demo traces, under project 'immune'.

Start Phoenix first:   uv run --extra agent phoenix serve   (UI at http://localhost:6006)
Then seed it:          uv run --extra agent python scripts/phoenix_seed.py

Sends one benchmark_turn span per question, plus a shadow_replay_attribution
child span (with culprit / confidence / trust-delta) for each failure — so you
can click through the same loop the dashboard shows.
"""
from __future__ import annotations

import os

from phoenix.otel import register

ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
tracer_provider = register(project_name="immune", endpoint=f"{ENDPOINT}/v1/traces",
                           set_global_tracer_provider=True)
tracer = tracer_provider.get_tracer("immune")

from immune import Agent, ImmuneMemory, ShadowReplay, score, scenario
from immune.tracing import set_admitted_memories, set_culprit_memories


def _span_id(span) -> str:
    return format(span.get_span_context().span_id, "016x")


def _run_benchmark(mode: str) -> list[dict]:
    """Trace one full benchmark for `mode` ('naive' or 'immune'); return eval records.
    naive  = no immune layer (true baseline).
    immune = shadow-replay heals failures in place.
    """
    store = ImmuneMemory(gate=(mode == "immune"), threshold=0.3)
    scenario.build_world(store)
    agent = Agent(store)
    replay = ShadowReplay(store) if mode == "immune" else None
    evals = []

    for turn in scenario.benchmark():
        with tracer.start_as_current_span("benchmark_turn") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")
            span.set_attribute("mode", mode)
            span.set_attribute("input.value", turn.question)
            span.set_attribute("expected", turn.expected)
            ans, admitted = agent.answer(turn.question)
            turn.answer, turn.admitted_ids = ans, admitted
            turn.correct = score(ans, turn.expected)
            span.set_attribute("output.value", ans)
            span.set_attribute("correct", turn.correct)
            span.set_attribute("admitted_ids", ", ".join(admitted))
            set_admitted_memories(span, store, admitted)

            if mode == "immune" and not turn.correct:
                with tracer.start_as_current_span("shadow_replay_attribution") as attr:
                    before = {m["id"]: m["trust"] for m in store.snapshot()}
                    act = replay.handle_failure(turn)
                    attr.set_attribute("openinference.span.kind", "CHAIN")
                    attr.set_attribute("confidence", act["confidence"])
                    attr.set_attribute("action", act["action"])
                    attr.set_attribute("culprits", ", ".join(act["culprits"]))
                    set_culprit_memories(attr, store, act["culprits"])
                    for mid in act["culprits"]:
                        m = store.get(mid)
                        if m:
                            attr.set_attribute(f"trust_before.{mid}", round(before.get(mid, 0), 3))
                            attr.set_attribute(f"trust_after.{mid}", round(m.trust, 3))
                ans, _ = agent.answer(turn.question)
                turn.correct = score(ans, turn.expected)
                span.set_attribute("healed_answer", ans)
                span.set_attribute("healed_correct", turn.correct)

            evals.append({"span_id": _span_id(span), "mode": mode,
                          "expected": turn.expected, "correct": turn.correct})
    return evals


# one eval name per mode → Phoenix shows two pass-rates side by side (the value)
_EVAL_NAME = {"naive": "answer_quality_naive", "immune": "answer_quality_immune"}


def log_evals(client, evals: list[dict]) -> None:
    for e in evals:
        client.spans.add_span_annotation(
            span_id=e["span_id"], annotation_name=_EVAL_NAME[e["mode"]],
            annotator_kind="CODE",
            label="pass" if e["correct"] else "fail",
            score=1.0 if e["correct"] else 0.0,
            explanation=f"answer vs ground truth '{e['expected']}' ({e['mode']})")


if __name__ == "__main__":
    all_evals = []
    runs = int(os.getenv("SEED_RUNS", "3"))     # fewer for live mode (saves API calls)
    for i in range(1, runs + 1):
        all_evals += _run_benchmark("naive")
        all_evals += _run_benchmark("immune")
        print(f"  run {i}: seeded naive + immune benchmarks")
    tracer_provider.force_flush()

    from phoenix.client import Client
    client = Client(base_url=ENDPOINT)
    log_evals(client, all_evals)

    def rate(mode):
        rows = [e for e in all_evals if e["mode"] == mode]
        return sum(e["correct"] for e in rows), len(rows)
    nok, nn = rate("naive"); iok, ii = rate("immune")
    print(f"\nSeeded project 'immune' at {ENDPOINT}.")
    print(f"  answer_quality_naive  : {nok}/{nn} pass  ({nok/nn:.0%})")
    print(f"  answer_quality_immune : {iok}/{ii} pass  ({iok/ii:.0%})")
    print(f"  -> IMMUNE lifts answer quality {nok/nn:.0%} -> {iok/ii:.0%}. That's the value, on screen in Arize.")
