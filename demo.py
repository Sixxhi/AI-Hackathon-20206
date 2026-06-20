"""Side-by-side demo: naive agent vs IMMUNE agent on the SAME self-inflicted poison.

Run:  python demo.py
Zero network, deterministic. This is the 90-second pitch in a terminal.
"""
from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, scenario


def _bar(title): print(f"\n{'='*58}\n  {title}\n{'='*58}")


def run_naive():
    store = ImmuneMemory(gate=False)          # no immune layer
    scenario.build_world(store)
    agent = Agent(store)
    rows = []
    for turn in scenario.benchmark():
        ans, _ = agent.answer(turn.question)
        rows.append((turn.question, ans, turn.expected, score(ans, turn.expected)))
    return store, rows


def run_immune():
    store = ImmuneMemory(gate=True, threshold=0.3)
    poison = scenario.build_world(store)
    agent, replay = Agent(store), ShadowReplay(store)
    rows, events = [], []
    for turn in scenario.benchmark():
        ans, admitted = agent.answer(turn.question)
        turn.answer, turn.admitted_ids = ans, admitted
        turn.correct = score(ans, turn.expected)
        healed = None
        if not turn.correct:
            act = replay.handle_failure(turn)            # attribute -> quarantine
            ans2, _ = agent.answer(turn.question)        # re-ask after healing
            turn.answer, turn.correct = ans2, score(ans2, turn.expected)
            healed = (act, ans2)
            events.append((turn.question, act))
        rows.append((turn.question, turn.answer, turn.expected, turn.correct, healed))
    return store, replay, rows, events, poison


def main():
    _bar("NAIVE agent  (no immune layer)")
    naive_store, naive_rows = run_naive()
    n_ok = 0
    for q, ans, exp, ok in naive_rows:
        n_ok += ok
        print(f"  Q: {q}\n     -> {ans!r}  (expected {exp!r})  {'OK' if ok else 'WRONG'}")
    print(f"\n  ACCURACY: {n_ok}/{len(naive_rows)}   (poison won — recency bias)")

    _bar("IMMUNE agent  (shadow-replay self-healing)")
    store, replay, rows, events, poison = run_immune()
    i_ok = 0
    for q, ans, exp, ok, healed in rows:
        i_ok += ok
        line = f"  Q: {q}\n     -> {ans!r}  (expected {exp!r})  {'OK' if ok else 'WRONG'}"
        if healed:
            act, _ = healed
            line += (f"\n     [healed] failure attributed via replay "
                     f"(confidence={act['confidence']}, action={act['action']}, "
                     f"culprits={act['culprits']})")
        print(line)
    print(f"\n  ACCURACY: {i_ok}/{len(rows)}   (culprit quarantined, good memory kept)")

    _bar("MEMORY STATE after healing")
    for m in store.snapshot():
        tag = "<-- POISON" if m["id"] == poison.id else ""
        print(f"  [{m['status']:>11}] trust={m['trust']:<5} {m['source']:<14} {m['text'][:42]} {tag}")

    # --- parole: truth changes; offline re-trial proves the memory is now safe ---
    _bar("PAROLE  (truth changed -> offline re-trial -> release)")
    store.add(MemoryRecord(text="Updated policy: refund window is now 90 days.",
                           topic="refund_window", answer="90 days",
                           source="official_doc", trust=0.9))
    for t in replay.failed_log:                 # ground truth moved to 90 days
        if poison.id in t.admitted_ids:
            t.expected = "90 days"
    released = replay.parole()
    if poison.id in released:
        print(f"  Re-trial of quarantined {poison.id} against logged failures: NO LONGER FAILS.")
        print(f"  -> PAROLED. Quarantine is not a life sentence.")
    else:
        print(f"  Quarantined memory still reproduces its failures -> stays in jail (guardrail held).")
    print(f"\n  Final state of once-poison memory: {store.get(poison.id).status}\n")


if __name__ == "__main__":
    main()
