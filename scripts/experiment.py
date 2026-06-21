"""Experiment: naive vs IMMUNE accuracy comparison.

Runs the IMMUNE benchmark in both modes and prints a side-by-side accuracy
table. If PHOENIX_COLLECTOR_ENDPOINT is set, sends experiment spans to Phoenix
so the before/after is visible in the Arize UI — this is criterion 4
("use feedback to make your app better").

Usage:
    uv run scripts/experiment.py                                   # offline
    IMMUNE_LIVE=1 uv run --extra agent --env-file .env \\
        scripts/experiment.py                                      # live Claude
    PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006 \\
        uv run --extra agent scripts/experiment.py                 # + Phoenix UI
"""
from __future__ import annotations

import os
import sys
import time

# allow running from repo root without install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, scenario
from immune import config


# ── tracing (optional — no-ops if Phoenix not running) ────────────────────────

_tracer = None

def _init_tracing() -> None:
    global _tracer
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "")
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider = TracerProvider(resource=Resource(attributes={
            "service.name": "immune-experiment",
            "project.name": config.ARIZE_PROJECT_NAME,
        }))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("immune-experiment")
        print(f"  Tracing → {endpoint}/projects  (project: {config.ARIZE_PROJECT_NAME})")
    except ImportError:
        pass


class _noop:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def set_attribute(self, *_): pass


def _span(name: str, **attrs):
    if _tracer is None:
        return _noop()
    return _tracer.start_as_current_span(name, attributes={
        "openinference.span.kind": "CHAIN", **attrs
    })


def _flush() -> None:
    if _tracer is None:
        return
    try:
        from opentelemetry import trace
        trace.get_tracer_provider().force_flush()
    except Exception:
        pass


# ── benchmark runners ──────────────────────────────────────────────────────────

def run_naive() -> list[dict]:
    store = ImmuneMemory(gate=False)
    scenario.build_world(store)
    agent = Agent(store)
    results = []
    for turn in scenario.benchmark():
        with _span("turn_naive", **{"input.value": turn.question,
                                    "experiment.mode": "naive",
                                    "expected": turn.expected}) as sp:
            ans, _ = agent.answer(turn.question)
            ok = score(ans, turn.expected)
            sp.set_attribute("output.value", ans)
            sp.set_attribute("correct", ok)
        results.append({"question": turn.question, "expected": turn.expected,
                        "answer": ans, "correct": ok})
    return results


def run_immune() -> list[dict]:
    store = ImmuneMemory(gate=True, threshold=config.TRUST_THRESHOLD)
    scenario.build_world(store)
    agent = Agent(store)
    replay = ShadowReplay(store)
    results = []

    for turn in scenario.benchmark():
        with _span("turn_immune", **{"input.value": turn.question,
                                     "experiment.mode": "immune",
                                     "expected": turn.expected}) as sp:
            ans, admitted = agent.answer(turn.question)
            turn.answer, turn.admitted_ids = ans, admitted
            turn.correct = score(ans, turn.expected)

            if not turn.correct:
                act = replay.handle_failure(turn)
                ans2, _ = agent.answer(turn.question)
                turn.answer = ans2
                turn.correct = score(ans2, turn.expected)
                sp.set_attribute("healed", True)
                sp.set_attribute("culprits", ", ".join(act["culprits"]))
                sp.set_attribute("action", act["action"])

            sp.set_attribute("output.value", turn.answer)
            sp.set_attribute("correct", turn.correct)
            results.append({"question": turn.question, "expected": turn.expected,
                            "answer": turn.answer, "correct": turn.correct})

    return results


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    _init_tracing()
    mode = "live-Claude" if config.USE_CLAUDE else "offline-mock"
    print(f"\n  IMMUNE experiment  [{mode}]")
    print(f"  {'─' * 54}")

    t0 = time.time()

    with _span("experiment_naive", **{"experiment.name": "naive-vs-immune",
                                      "experiment.mode": "naive"}):
        naive = run_naive()

    with _span("experiment_immune", **{"experiment.name": "naive-vs-immune",
                                       "experiment.mode": "immune"}):
        immune = run_immune()

    elapsed = time.time() - t0

    # ── print comparison table ─────────────────────────────────────────────────
    PASS = "\033[92m✓\033[0m"
    FAIL = "\033[91m✗\033[0m"
    print()
    print(f"  {'Question':<42} {'Naive':>6}  {'IMMUNE':>6}")
    print(f"  {'─' * 42}  {'─' * 6}  {'─' * 6}")
    for n, i in zip(naive, immune):
        n_mark = PASS if n["correct"] else FAIL
        i_mark = PASS if i["correct"] else FAIL
        print(f"  {n['question']:<42} {n_mark:>6}  {i_mark:>6}")

    n_acc = sum(r["correct"] for r in naive)
    i_acc = sum(r["correct"] for r in immune)
    total = len(naive)
    delta = i_acc - n_acc

    print(f"  {'─' * 42}  {'─' * 6}  {'─' * 6}")
    print(f"  {'ACCURACY':<42} {n_acc}/{total}    {i_acc}/{total}")
    print()

    if delta > 0:
        print(f"  \033[92m+{delta} question(s) healed by IMMUNE\033[0m"
              " — quarantine made the agent better.")
    elif delta == 0:
        print("  Accuracy unchanged (Claude may have used trust scores to avoid poison).")
    else:
        print(f"  \033[91mIMMUNE worse by {abs(delta)}\033[0m — investigate.")

    print(f"\n  Elapsed: {elapsed:.1f}s")

    if _tracer:
        print("\n  Flushing spans to Phoenix...")
        _flush()
        endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "")
        print(f"  → {endpoint}/projects  (look for project '{config.ARIZE_PROJECT_NAME}')")

    print()


if __name__ == "__main__":
    main()
