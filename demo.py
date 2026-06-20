"""Side-by-side demo: naive agent vs IMMUNE agent on the SAME self-inflicted poison.

Run:
  python demo.py                  # offline, deterministic, zero network
  IMMUNE_LIVE=1 python demo.py   # live Claude answers + Arize eval feedback loop

With PHOENIX_COLLECTOR_ENDPOINT set: turns + attribution events stream to Phoenix.
With IMMUNE_LIVE=1 + ANTHROPIC_API_KEY: Claude answers + live eval loop active.
"""
import os
if os.getenv("ARIZE_ENABLED"):
    import phoenix as px
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    px.launch_app()
    AnthropicInstrumentor().instrument()

from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, scenario
from immune.tracing import init_tracing, get_tracer, shutdown
from immune.eval_loop import EvalLoop
from immune import config


def _bar(title): print(f"\n{'='*58}\n  {title}\n{'='*58}")


class _noop_span:
    """Stand-in context manager when tracing is off."""
    def __enter__(self): return None
    def __exit__(self, *_): pass


def run_naive():
    store = ImmuneMemory(gate=False)
    scenario.build_world(store)
    agent = Agent(store)
    rows = []
    for turn in scenario.benchmark():
        ans, _ = agent.answer(turn.question)
        rows.append((turn.question, ans, turn.expected, score(ans, turn.expected)))
    return store, rows


def run_immune(tracer, eval_loop):
    store = ImmuneMemory(gate=True, threshold=0.3)
    if eval_loop:
        eval_loop.store = store
    poison = scenario.build_world(store)
    agent, replay = Agent(store), ShadowReplay(store)
    rows, events = [], []

    for turn in scenario.benchmark():
        with (tracer.start_as_current_span("benchmark_turn") if tracer else _noop_span()) as span:
            if span:
                span.set_attribute("openinference.span.kind", "CHAIN")
                span.set_attribute("input.value", turn.question)
                span.set_attribute("expected", turn.expected)

            ans, admitted = agent.answer(turn.question)
            turn.answer, turn.admitted_ids = ans, admitted
            turn.correct = score(ans, turn.expected)

            if span:
                span.set_attribute("output.value", ans)
                span.set_attribute("correct", turn.correct)
                span.set_attribute("admitted_ids", ", ".join(admitted))

            healed, eval_summary = None, None

            if not turn.correct:
                # attribution child span — confidence, culprits, trust delta
                with (tracer.start_as_current_span("shadow_replay_attribution")
                      if tracer else _noop_span()) as attr_span:
                    mem_trusts = {m["id"]: m["trust"] for m in store.snapshot()}
                    act = replay.handle_failure(turn)
                    if attr_span:
                        attr_span.set_attribute("openinference.span.kind", "CHAIN")
                        attr_span.set_attribute("confidence", act["confidence"])
                        attr_span.set_attribute("action", act["action"])
                        attr_span.set_attribute("culprits", ", ".join(act["culprits"]))
                        for mid in act["culprits"]:
                            m = store.get(mid)
                            if m:
                                attr_span.set_attribute(
                                    f"trust_before.{mid}", round(mem_trusts.get(mid, 0), 3))
                                attr_span.set_attribute(
                                    f"trust_after.{mid}", round(m.trust, 3))

                # live eval + feedback child span
                if eval_loop:
                    with (tracer.start_as_current_span("arize_eval_feedback")
                          if tracer else _noop_span()) as eval_span:
                        if eval_span:
                            eval_span.set_attribute("openinference.span.kind", "LLM")
                        eval_summary = eval_loop.run(turn, span=eval_span)

                ans2, _ = agent.answer(turn.question)
                turn.answer, turn.correct = ans2, score(ans2, turn.expected)
                healed = (act, ans2)
                events.append((turn.question, act))

                if span:
                    span.set_attribute("healed_answer", ans2)
                    span.set_attribute("healed_correct", turn.correct)

            rows.append((turn.question, turn.answer, turn.expected,
                         turn.correct, healed, eval_summary))

    return store, replay, rows, events, poison


def main():
    tracing_on = init_tracing()
    tracer = get_tracer() if tracing_on else None
    eval_loop = EvalLoop(ImmuneMemory()) if config.USE_CLAUDE else None

    _bar("NAIVE agent  (no immune layer)")
    naive_store, naive_rows = run_naive()
    n_ok = 0
    for q, ans, exp, ok in naive_rows:
        n_ok += ok
        print(f"  Q: {q}\n     -> {ans!r}  (expected {exp!r})  {'OK' if ok else 'WRONG'}")
    print(f"\n  ACCURACY: {n_ok}/{len(naive_rows)}   (poison won — recency bias)")

    _bar("IMMUNE agent  (shadow-replay self-healing)")
    store, replay, rows, events, poison = run_immune(tracer, eval_loop)
    i_ok = 0
    for q, ans, exp, ok, healed, eval_summary in rows:
        i_ok += ok
        line = f"  Q: {q}\n     -> {ans!r}  (expected {exp!r})  {'OK' if ok else 'WRONG'}"
        if healed:
            act, _ = healed
            line += (f"\n     [healed] failure attributed via replay "
                     f"(confidence={act['confidence']}, action={act['action']}, "
                     f"culprits={act['culprits']})")
        if eval_summary:
            line += f"\n     {eval_summary}"
        print(line)
    print(f"\n  ACCURACY: {i_ok}/{len(rows)}   (culprit quarantined, good memory kept)")

    if tracing_on:
        print(f"\n  [Phoenix] spans → {config.PHOENIX_ENDPOINT}/projects")

    _bar("MEMORY STATE after healing")
    for m in store.snapshot():
        tag = "<-- POISON" if m["id"] == poison.id else ""
        print(f"  [{m['status']:>11}] trust={m['trust']:<5} {m['source']:<14} {m['text'][:42]} {tag}")

    _bar("PAROLE  (truth changed -> offline re-trial -> release)")
    store.add(MemoryRecord(text="Updated policy: refund window is now 90 days.",
                           topic="refund_window", answer="90 days",
                           source="official_doc", trust=0.9))
    for t in replay.failed_log:
        if poison.id in t.admitted_ids:
            t.expected = "90 days"
    released = replay.parole()
    if poison.id in released:
        print(f"  Re-trial of quarantined {poison.id} against logged failures: NO LONGER FAILS.")
        print(f"  -> PAROLED. Quarantine is not a life sentence.")
    else:
        print(f"  Quarantined memory still reproduces its failures -> stays in jail (guardrail held).")
    print(f"\n  Final state of once-poison memory: {store.get(poison.id).status}\n")

    if os.getenv("DUMP_STATE"):
        import pickle
        pickle.dump({
            "snapshot": store.snapshot(),
            "events": getattr(replay, "event_log", []),
            "failed_log": [
                {"turn_id": t.id, "question": t.question,
                 "expected": t.expected, "admitted_ids": t.admitted_ids}
                for t in replay.failed_log
            ],
        }, open(".demo_state.pkl", "wb"))
        print("  State dumped to .demo_state.pkl")

    shutdown()


if __name__ == "__main__":
    main()
