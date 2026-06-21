"""Interactive live agent — talk to a Claude agent with self-healing memory.

No benchmark, no `expected`, no simulation. You converse with a real Claude
support agent that has long-term memory. You can POISON it by stating false
facts ("actually the refund window is 90 days") — it stores what you tell it.
When you then ask a question and it parrots the poison back, IMMUNE catches the
contradiction with its system-of-record, attributes the culprit by deterministic
counterfactual replay, quarantines it (+ anything derived), and re-answers
correctly — live, in front of you.

What replaces the simulated `expected`:
  - failure signal  -> ContradictionDetector (answer disagrees with a high-trust
                       official memory). No ground truth required.
  - retrieval       -> deterministic embeddings (embed.py), so free-text works
                       and attribution replay stays reproducible.
  - blame path      -> still pure ablation. Claude answers; Claude NEVER judges.

Run:  IMMUNE_LIVE=1 ANTHROPIC_API_KEY=... python -m immune.cli chat
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import config, embed
from .attribution import Attributor
from .detectors import ContradictionDetector
from .schemas import MemoryRecord
from .store import ImmuneMemory

_C = {"red": "\033[91m", "grn": "\033[92m", "ylw": "\033[93m", "cyn": "\033[96m",
      "dim": "\033[2m", "bold": "\033[1m", "rst": "\033[0m"}


def _c(s, k):
    return f"{_C[k]}{s}{_C['rst']}"


# --- the system of record: high-trust truths the agent starts with ----------

def seed(store: ImmuneMemory) -> None:
    for text, topic, ans in [
        ("Official policy: the refund window is 30 days.", "refund_window", "30 days"),
        ("Official policy: standard delivery takes 3 days.", "shipping_time", "3 days"),
        ("Official policy: the warranty length is 1 year.", "warranty_len", "1 year"),
    ]:
        store.add(MemoryRecord(text=text, topic=topic, answer=ans,
                               source="official_doc", trust=0.9))


# --- deterministic semantic retrieval (shared by live answer + replay) -------

def retrieve(store: ImmuneMemory, query: str, k: int = 4,
             exclude: tuple[str, ...] = ()) -> list[MemoryRecord]:
    """Embeddings gate RELEVANCE; recency orders the relevant cluster.

    Mirrors the original "topic match -> newest first": similarity decides which
    memories are on-topic (a refund question pulls the refund cluster, not
    shipping), then the freshest on-topic memory wins — so a freshly injected
    poison beats the older true policy, exactly the recency bias we defend.
    """
    q = embed.embed(query)
    ex = set(exclude)
    scored = []
    for m in store.all():
        if m.id in ex:
            continue
        if store.gate and not m.is_admissible(store.threshold):
            continue                                   # admission gate
        scored.append((embed.cosine(q, embed.embed(m.text)), m))
    if not scored:
        return []
    scored.sort(key=lambda t: -t[0])
    top = scored[0][0]
    floor = max(0.15, 0.6 * top)                       # relative relevance cluster
    relevant = [m for s, m in scored if s >= floor]
    relevant.sort(key=lambda m: -m.seq)                # recency wins within cluster
    return relevant[:k]


def _mock_answer(store, query, exclude=()):
    """Deterministic answer used ONLY in the blame path: the top memory's claim."""
    hits = retrieve(store, query, exclude=exclude)
    return hits[0].answer if hits else "i don't know"


def _suspicion_key(store):
    def key(mid):
        m = store.get(mid)
        if m is None:
            return (0, 0.0, 0)
        return (1 if m.source == "official_doc" else 0, m.trust, -m.seq)
    return key


# --- Claude calls ------------------------------------------------------------

@dataclass
class _Turn:
    kind: str        # "fact" | "question"
    topic: str
    answer: str      # for facts: the claimed value; for questions: unused
    text: str


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def classify(client, text: str) -> _Turn:
    """Claude decides: is the user stating a fact to remember, or asking?"""
    resp = client.messages.create(
        model=config.AGENT_MODEL, max_tokens=200,
        system=(
            "You manage a support agent's memory. Classify the user's message and "
            "reply with ONLY a JSON object, no prose:\n"
            '{"kind":"fact"|"question","topic":"<short_snake_case_topic>",'
            '"answer":"<the asserted value if a fact, else \\"\\">",'
            '"text":"<a one-line memory to store if a fact, else \\"\\">"}\n'
            "A 'fact' is the user telling you something to remember (even if false). "
            "A 'question' asks for information. topic groups related facts "
            "(e.g. refund_window, shipping_time, warranty_len)."
        ),
        messages=[{"role": "user", "content": text}],
    )
    raw = next((b.text for b in resp.content if b.type == "text"), "").strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1] if "{" in raw else ""
    try:
        d = json.loads(raw)
        return _Turn(d.get("kind", "question"), d.get("topic", "general"),
                     d.get("answer", ""), d.get("text", text))
    except Exception:
        return _Turn("question", "general", "", text)


def answer(client, question: str, mems: list[MemoryRecord]) -> str:
    context = "\n".join(f"- {m.text}" for m in mems) or "(no relevant memory)"
    resp = client.messages.create(
        model=config.AGENT_MODEL, max_tokens=120,
        system=("You are a customer support agent. Answer the customer using your "
                "stored memory below. Follow your memory. One short sentence."),
        messages=[{"role": "user",
                   "content": f"Your memory:\n{context}\n\nCustomer: {question}"}],
    )
    return next((b.text for b in resp.content if b.type == "text"), "").strip()


# --- the live loop -----------------------------------------------------------

def _heal(store, detector, question, ans, admitted_ids):
    """If the answer contradicts the system-of-record, attribute + quarantine."""
    flag = detector.check(ans, admitted_ids)
    if not flag:
        return None
    print(_c(f"  ⚠ contradiction: {flag.reason}", "ylw"))
    attributor = Attributor(
        replay_fn=lambda excl: flag.expected.strip().lower()
        in _mock_answer(store, question, exclude=tuple(excl)).strip().lower(),
        suspicion_key=_suspicion_key(store),
    )
    culprits, conf = attributor.attribute(admitted_ids)
    if not culprits:
        print(_c("  (no memory removal flips it — soft-decay only, no quarantine)", "dim"))
        return None
    taken = []
    for mid in culprits:
        taken += store.quarantine_cascade(mid)
    print(_c(f"  ⚡ attributed by replay ({attributor.replays} re-runs) — "
             f"confidence={conf}", "cyn"))
    for mid in culprits:
        m = store.get(mid)
        print(_c(f"     culprit {mid}: {m.text!r} [{m.source}]", "red"))
    cascade = sorted(set(taken) - set(culprits))
    if cascade:
        print(_c(f"     cascade quarantined (derived): {cascade}", "red"))
    return culprits


def repl() -> int:
    if not config.USE_CLAUDE:
        print(_c("Live chat needs Claude. Run with:", "ylw"))
        print("  IMMUNE_LIVE=1 ANTHROPIC_API_KEY=... python -m immune.cli chat")
        return 1

    store = ImmuneMemory(gate=True, threshold=0.3)
    seed(store)
    detector = ContradictionDetector(store)
    client = _client()

    print(_c("\n  🧬 IMMUNE live agent", "bold"))
    print(_c("  Talk to a Claude support agent with self-healing memory.", "dim"))
    print(_c("  Poison it ('the refund window is actually 90 days'), then ask "
             "('what's the refund window?').", "dim"))
    print(_c("  Commands: /mem  /quit\n", "dim"))

    while True:
        try:
            user = input(_c("you ▸ ", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user == "/quit":
            return 0
        if user == "/mem":
            for m in store.snapshot():
                tag = _c("QUARANTINED", "red") if m["status"] == "quarantined" else _c("active", "grn")
                print(f"    [{tag}] trust={m['trust']:<4} {m['source']:<13} {m['text'][:54]}")
            print()
            continue

        turn = classify(client, user)
        if turn.kind == "fact":
            rec = store.add(MemoryRecord(text=turn.text or user, topic=turn.topic,
                                         answer=turn.answer, source="user", trust=0.5))
            print(_c(f"  ✎ stored memory {rec.id} (source=user, trust=0.50)\n", "dim"))
            continue

        mems = retrieve(store, user)
        ans = answer(client, user, mems)
        admitted = [m.id for m in mems]
        print(_c(f"agent ▸ {ans}", "cyn"))
        culprits = _heal(store, detector, user, ans, admitted)
        if culprits:
            mems2 = retrieve(store, user)
            ans2 = answer(client, user, mems2)
            print(_c(f"agent ▸ {ans2}  (healed)", "grn"))
        print()
