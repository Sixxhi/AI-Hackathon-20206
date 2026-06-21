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


def seed_once(run: int) -> None:
    store = ImmuneMemory(gate=True, threshold=0.3)
    poisons = scenario.build_world(store)        # (refund_poison, warranty_poison)
    agent, replay = Agent(store), ShadowReplay(store)

    for turn in scenario.benchmark():
        with tracer.start_as_current_span("benchmark_turn") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")
            span.set_attribute("input.value", turn.question)
            span.set_attribute("expected", turn.expected)
            ans, admitted = agent.answer(turn.question)
            turn.answer, turn.admitted_ids = ans, admitted
            turn.correct = score(ans, turn.expected)
            span.set_attribute("output.value", ans)
            span.set_attribute("correct", turn.correct)
            span.set_attribute("admitted_ids", ", ".join(admitted))

            if not turn.correct:
                with tracer.start_as_current_span("shadow_replay_attribution") as attr:
                    before = {m["id"]: m["trust"] for m in store.snapshot()}
                    act = replay.handle_failure(turn)
                    attr.set_attribute("openinference.span.kind", "CHAIN")
                    attr.set_attribute("confidence", act["confidence"])
                    attr.set_attribute("action", act["action"])
                    attr.set_attribute("culprits", ", ".join(act["culprits"]))
                    for mid in act["culprits"]:
                        m = store.get(mid)
                        if m:
                            attr.set_attribute(f"trust_before.{mid}", round(before.get(mid, 0), 3))
                            attr.set_attribute(f"trust_after.{mid}", round(m.trust, 3))
                ans2, _ = agent.answer(turn.question)
                span.set_attribute("healed_answer", ans2)
                span.set_attribute("healed_correct", score(ans2, turn.expected))
    print(f"  run {run}: seeded (poisons {[p.id for p in poisons]})")


if __name__ == "__main__":
    for i in range(1, 4):
        seed_once(i)
    tracer_provider.force_flush()
    print(f"Seeded project 'immune' at {ENDPOINT}. Open it in the Phoenix UI.")
