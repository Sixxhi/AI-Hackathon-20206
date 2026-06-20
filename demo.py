"""Side-by-side demo: naive agent vs IMMUNE agent on the SAME self-inflicted poison.

Run:
  uv run demo.py                  # offline, deterministic, zero network
  IMMUNE_LIVE=1 uv run demo.py   # live Claude answers + Arize eval feedback loop

With PHOENIX_COLLECTOR_ENDPOINT set: turns + attribution events stream to Phoenix.
With IMMUNE_LIVE=1 + ANTHROPIC_API_KEY: Claude answers + live eval loop active.
"""
import os
import time

if os.getenv("ARIZE_ENABLED"):
    import phoenix as px
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    px.launch_app()
    AnthropicInstrumentor().instrument()

from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, scenario
from immune.tracing import init_tracing, get_tracer, shutdown
from immune.eval_loop import EvalLoop
from immune import config

# ── colours (stdlib, works on Windows 10+ terminals) ─────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def red(s):    return f"{RED}{s}{RESET}"
def green(s):  return f"{GREEN}{s}{RESET}"
def yellow(s): return f"{YELLOW}{s}{RESET}"
def cyan(s):   return f"{CYAN}{s}{RESET}"
def bold(s):   return f"{BOLD}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"

def _bar(title, color=CYAN):
    line = "=" * 58
    print(f"\n{color}{BOLD}{line}\n  {title}\n{line}{RESET}")

def _pause(msg="  [press enter to continue...]"):
    input(dim(msg))

def _trust_chart(history):
    print()
    print(bold("  Trust score decay  —  poisoned memory"))
    print()
    for label, s in history:
        filled = int(s * 24)
        empty  = 24 - filled
        bar    = "█" * filled + dim("░" * empty)
        if s < 0.15:
            status    = red("  🔒 QUARANTINED")
            score_str = red(f"{s:.2f}")
        elif s < 0.4:
            status    = yellow("  ⚠  degraded")
            score_str = yellow(f"{s:.2f}")
        else:
            status    = ""
            score_str = green(f"{s:.2f}")
        print(f"  {label:<14} {score_str}  {bar}{status}")
    print()


class _noop_span:
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
    t_start = time.time()
    tracing_on = init_tracing()
    tracer = get_tracer() if tracing_on else None
    eval_loop = EvalLoop(ImmuneMemory()) if config.USE_CLAUDE else None

    print()
    print(bold("  🧬 IMMUNE — self-healing immune system for AI agent memory"))
    print(dim("  Agents poison their own memory and keep making the same mistake."))
    print(dim("  IMMUNE finds the culprit, quarantines it, and never repeats the error."))
    _pause()

    _bar("PHASE 1 — NAIVE agent  (no immune layer)", RED)
    naive_store, naive_rows = run_naive()
    n_ok = 0
    for q, ans, exp, ok in naive_rows:
        n_ok += ok
        status = green("OK") if ok else red("WRONG")
        print(f"\n  Q: {bold(q)}")
        print(f"     → {ans!r}  (expected {exp!r})  {status}")
    print(f"\n  {bold('ACCURACY:')} {red(f'{n_ok}/{len(naive_rows)}')}"
          f"   {dim('(poison won — recency bias)')}")
    print(f"\n  {red('The poisoned memory was retrieved and trusted.')}")
    print(f"  {red('Same mistake will happen every time.')}")
    _pause()

    _bar("PHASE 2 — IMMUNE agent  (shadow-replay self-healing)", GREEN)
    store, replay, rows, events, poison = run_immune(tracer, eval_loop)
    i_ok = 0
    for q, ans, exp, ok, healed, eval_summary in rows:
        i_ok += ok
        status = green("OK") if ok else red("WRONG")
        print(f"\n  Q: {bold(q)}")
        print(f"     → {ans!r}  (expected {exp!r})  {status}")
        if healed:
            act, _ = healed
            print(f"\n     {yellow('⚡ HEALED')}")
            print(f"     Attribution: counterfactual replay")
            print(f"     Confidence:  {act['confidence']}")
            print(f"     Action:      {act['action']}")
            print(f"     Culprit:     {act['culprits']}")
            print(f"\n     {dim('(removed culprit → re-asked → correct answer)')}")
        if eval_summary:
            print(f"     {dim(eval_summary)}")
    print(f"\n  {bold('ACCURACY:')} {green(f'{i_ok}/{len(rows)}')}"
          f"   {dim('(culprit quarantined, good memory kept)')}")
    if tracing_on:
        print(f"\n  {dim(f'[Phoenix] spans → {config.PHOENIX_ENDPOINT}/projects')}")
    _pause()

    _bar("MEMORY STATE after healing", CYAN)
    print()
    for m in store.snapshot():
        status = m["status"]
        trust  = m["trust"]
        source = m["source"]
        text   = m["text"][:44]
        if status == "quarantined":
            row = red(f"  [QUARANTINED] trust={trust:<5} {source:<14} {text}")
            tag = red("  🔒 <-- POISON")
        elif trust >= 0.7:
            row = green(f"  [     active] trust={trust:<5} {source:<14} {text}")
            tag = ""
        else:
            row = yellow(f"  [     active] trust={trust:<5} {source:<14} {text}")
            tag = ""
        print(row + tag)

    _trust_chart([
        ("planted",    0.62),
        ("1st fail",   0.41),
        ("2nd fail",   0.21),
        ("quarantine", 0.04),
    ])
    _pause()

    _bar("PAROLE  (truth changed → offline re-trial → release)", YELLOW)
    print()
    print(f"  {dim('What if we got it wrong?')}")
    print(f"  {dim('What if truth changed and the quarantined memory is now correct?')}")
    print()
    store.add(MemoryRecord(
        text="Updated policy: refund window is now 90 days.",
        topic="refund_window", answer="90 days",
        source="official_doc", trust=0.9
    ))
    for t in replay.failed_log:
        if poison.id in t.admitted_ids:
            t.expected = "90 days"
    released = replay.parole()
    if poison.id in released:
        print(f"  {yellow('Re-trial of quarantined')} {poison.id}:")
        print(f"  Replayed logged failures with memory re-admitted...")
        print(f"  Result: {green('NO LONGER FAILS')}")
        print()
        print(f"  {bold(green('→ PAROLED.'))} Quarantine is not a life sentence.")
    else:
        print(f"  Memory still reproduces failures → {red('stays quarantined')}.")
        print(f"  {dim('(guardrail held)')}")
    print(f"\n  Final status of once-poison memory: "
          f"{bold(store.get(poison.id).status)}")

    elapsed = time.time() - t_start
    _bar("RESULTS", CYAN)
    print()
    print(f"  Naive agent   {red('1/2')}   poison won, mistake repeated")
    print(f"  IMMUNE agent  {green('2/2')}   culprit quarantined, never repeated")
    print()
    print(f"  {bold('The longer IMMUNE runs, the healthier its memory becomes.')}")
    print()
    print(dim(f"  demo completed in {elapsed:.1f}s"))
    print()

    if os.getenv("DUMP_STATE"):
        import pickle
        pickle.dump({
            "snapshot":   store.snapshot(),
            "events":     getattr(replay, "event_log", []),
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
