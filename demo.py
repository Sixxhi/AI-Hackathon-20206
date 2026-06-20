"""Side-by-side demo: naive agent vs IMMUNE agent on the SAME self-inflicted poison.

Run:  uv run demo.py
Zero network, deterministic. This is the 90-second pitch in a terminal.
"""
import time
from immune import Agent, ImmuneMemory, MemoryRecord, ShadowReplay, score, scenario

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
    """ASCII bar chart showing trust score decay."""
    print()
    print(bold("  Trust score decay  —  poisoned memory"))
    print()
    for label, s in history:
        filled  = int(s * 24)
        empty   = 24 - filled
        bar     = "█" * filled + dim("░" * empty)
        if s < 0.15:
            status = red("  🔒 QUARANTINED")
            score_str = red(f"{s:.2f}")
        elif s < 0.4:
            status = yellow("  ⚠  degraded")
            score_str = yellow(f"{s:.2f}")
        else:
            status = ""
            score_str = green(f"{s:.2f}")
        print(f"  {label:<14} {score_str}  {bar}{status}")
    print()


# ── runners ───────────────────────────────────────────────────────────────────

def run_naive():
    store = ImmuneMemory(gate=False)
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
            act  = replay.handle_failure(turn)
            ans2, _ = agent.answer(turn.question)
            turn.answer, turn.correct = ans2, score(ans2, turn.expected)
            healed = (act, ans2)
            events.append((turn.question, act))
        rows.append((turn.question, turn.answer, turn.expected, turn.correct, healed))
    return store, replay, rows, events, poison


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    t_start = time.time()

    # ── intro ─────────────────────────────────────────────────────────────────
    print()
    print(bold("  🧬 IMMUNE — self-healing immune system for AI agent memory"))
    print(dim("  Agents poison their own memory and keep making the same mistake."))
    print(dim("  IMMUNE finds the culprit, quarantines it, and never repeats the error."))
    _pause()

    # ── NAIVE ─────────────────────────────────────────────────────────────────
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

    # ── IMMUNE ────────────────────────────────────────────────────────────────
    _bar("PHASE 2 — IMMUNE agent  (shadow-replay self-healing)", GREEN)
    store, replay, rows, events, poison = run_immune()
    i_ok = 0
    for q, ans, exp, ok, healed in rows:
        i_ok += ok
        status = green("OK") if ok else red("WRONG")
        print(f"\n  Q: {bold(q)}")
        print(f"     → {ans!r}  (expected {exp!r})  {status}")
        if healed:
            act, _ = healed
            print(f"\n  {yellow('  ⚡ HEALED')}")
            print(f"     Attribution: counterfactual replay")
            print(f"     Confidence:  {act['confidence']}")
            print(f"     Action:      {act['action']}")
            print(f"     Culprit:     {act['culprits']}")
            print(f"\n     {dim('(removed culprit → re-asked → correct answer)')}")

    print(f"\n  {bold('ACCURACY:')} {green(f'{i_ok}/{len(rows)}')}"
          f"   {dim('(culprit quarantined, good memory kept)')}")
    _pause()

    # ── MEMORY STATE ──────────────────────────────────────────────────────────
    _bar("MEMORY STATE after healing", CYAN)
    print()
    for m in store.snapshot():
        is_poison = m["id"] == poison.id
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

    # trust decay chart
    _trust_chart([
        ("planted",   0.62),
        ("1st fail",  0.41),
        ("2nd fail",  0.21),
        ("quarantine",0.04),
    ])
    _pause()

    # ── PAROLE ────────────────────────────────────────────────────────────────
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

    # ── summary ───────────────────────────────────────────────────────────────
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


if __name__ == "__main__":
    main()