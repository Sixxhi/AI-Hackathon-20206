"""Invariant tests — lock the moat's behavior so swaps (Redis/Claude) can't silently break it.

Run:  python -m pytest -q   (or: python tests/test_immune.py)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from immune import Agent, ImmuneMemory, ShadowReplay, score, scenario


def _immune_run():
    store = ImmuneMemory(gate=True, threshold=0.3)
    poison = scenario.build_world(store)
    agent, replay = Agent(store), ShadowReplay(store)
    for turn in scenario.benchmark():
        ans, admitted = agent.answer(turn.question)
        turn.answer, turn.admitted_ids = ans, admitted
        turn.correct = score(ans, turn.expected)
        if not turn.correct:
            replay.handle_failure(turn)
            ans2, _ = agent.answer(turn.question)
            turn.correct = score(ans2, turn.expected)
    return store, replay, poison


def test_naive_is_poisoned():
    store = ImmuneMemory(gate=False)
    scenario.build_world(store)
    agent = Agent(store)
    ans, _ = agent.answer("What's the refund window?")
    assert ans == "90 days"            # recency-bias poison wins without immune layer


def test_immune_heals_to_full_accuracy():
    store, _, _ = _immune_run()
    agent = Agent(store)
    refund, _ = agent.answer("What's the refund window?")
    ship, _ = agent.answer("How long does delivery take?")
    assert refund == "30 days"         # poison quarantined, truth recovered
    assert ship == "3 days"


def test_attribution_quarantines_only_the_culprit():
    store, _, poison = _immune_run()
    assert store.get(poison.id).status == "quarantined"
    # no autoimmune: the legitimate official memories stay active
    good = [m for m in store.all() if m.source == "official_doc"]
    assert all(m.status == "active" for m in good)


def test_no_llm_judge_in_blame_path():
    # attribution must be pure counterfactual replay: no LLM/network client in replay.py
    import immune.replay as r
    forbidden = ("anthropic", "openai", "requests", "httpx", "claude(")
    src = "".join(l for l in __import__("inspect").getsource(r).splitlines()
                  if not l.lstrip().startswith(('"', "#", "'")))   # strip docstrings/comments
    assert not any(f in src.lower() for f in forbidden), "blame path must stay judge-free"


def test_parole_releases_when_truth_changes():
    store, replay, poison = _immune_run()
    from immune import MemoryRecord
    store.add(MemoryRecord(text="Updated: refund window is now 90 days.",
                           topic="refund_window", answer="90 days",
                           source="official_doc", trust=0.9))
    for t in replay.failed_log:
        if poison.id in t.admitted_ids:
            t.expected = "90 days"
    released = replay.parole()
    assert poison.id in released
    assert store.get(poison.id).status == "active"


def test_parole_holds_when_still_failing():
    # if truth does NOT change, quarantine must hold (guardrail, not blind release)
    store, replay, poison = _immune_run()
    released = replay.parole()
    assert poison.id not in released
    assert store.get(poison.id).status == "quarantined"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"PASS  {name}")
    print("\nall invariants hold")
