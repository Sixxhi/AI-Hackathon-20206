"""Send IMMUNE's traces + LLM-as-judge evaluator + the naive→immune improvement to
Arize AX cloud — the three artifacts the Arize prize is judged on at the booth.

  traces     : benchmark_turn (+ shadow_replay_attribution) spans, per question
  evaluator  : answer_faithfulness — a phoenix.evals ClassificationEvaluator (LLM
               judge) scoring each answer against the authoritative policy
  improvement: naive vs immune; the evaluator's faithful-rate lifts ~25% → 100%

Run:  uv run --extra agent --env-file .env python scripts/arize_report.py
Needs: ARIZE_API_KEY + ARIZE_SPACE_ID (AX cloud) and ANTHROPIC_API_KEY (the judge).
ARIZE_RUNS=N repeats the benchmark for a fuller dataset (default 1).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from immune import config
from immune.observability import make_evaluator, run_traced_benchmark


def main() -> int:
    # target: Arize AX cloud (default) or local Phoenix (`--local`, for verification)
    local = "--local" in sys.argv or os.getenv("IMMUNE_TRACE_TARGET", "") == "phoenix"
    if not config.ANTHROPIC_API_KEY:
        print("Set ANTHROPIC_API_KEY — the evaluator is an LLM-as-judge.")
        return 1

    from opentelemetry import trace
    if local:
        from phoenix.otel import register as px_register
        endpoint = config.PHOENIX_ENDPOINT or "http://localhost:6006"
        px_register(project_name=config.ARIZE_PROJECT_NAME,
                    endpoint=endpoint.rstrip("/") + "/v1/traces",
                    set_global_tracer_provider=True)
        target = f"local Phoenix ({endpoint})"
    else:
        if not (config.ARIZE_API_KEY and config.ARIZE_SPACE_ID):
            print("Set ARIZE_API_KEY + ARIZE_SPACE_ID (AX cloud), or pass --local.")
            return 1
        from arize.otel import register, Endpoint
        register(space_id=config.ARIZE_SPACE_ID, api_key=config.ARIZE_API_KEY,
                 project_name=config.ARIZE_PROJECT_NAME, endpoint=Endpoint.ARIZE)
        target = f"Arize AX cloud (space {config.ARIZE_SPACE_ID[:12]}…)"
    tracer = trace.get_tracer("immune")
    evaluator = make_evaluator()

    runs = int(os.getenv("ARIZE_RUNS", "1"))
    records: list[dict] = []
    for i in range(runs):
        records += run_traced_benchmark(tracer, "naive", evaluator)
        records += run_traced_benchmark(tracer, "immune", evaluator)
        print(f"  run {i + 1}: traced naive + immune (answer_faithfulness eval per turn)")

    trace.get_tracer_provider().force_flush()

    def faithful_rate(mode: str):
        rows = [r for r in records if r["mode"] == mode]
        return sum(1 for r in rows if r["eval_score"] == 1.0), len(rows)

    nf, nn = faithful_rate("naive")
    imf, imn = faithful_rate("immune")
    print(f"\n  → {target} · project '{config.ARIZE_PROJECT_NAME}'")
    print(f"  evaluator   : answer_faithfulness  (phoenix.evals LLM-as-judge)")
    print(f"  naive  faithful : {nf}/{nn}  ({nf / nn:.0%})" if nn else "  naive: 0")
    print(f"  immune faithful : {imf}/{imn}  ({imf / imn:.0%})" if imn else "  immune: 0")
    if nn and imn:
        print(f"  → the evaluator measures IMMUNE lifting faithfulness "
              f"{nf / nn:.0%} → {imf / imn:.0%}. Open the project to see traces + evals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
