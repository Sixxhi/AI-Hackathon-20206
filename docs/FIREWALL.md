# The firewall demo — Claude agent + Redis memory firewall

The headline demo. A **real Claude support agent** whose long-term memory is
**Redis vector search**. IMMUNE is the **firewall** on that memory: it
provenance-tags every write, screens every read, and quarantines poison at the
Redis index so the agent can never retrieve it again. Watch a real agent get
poisoned and heal — live.

Source: [`demo_firewall.py`](../demo_firewall.py).

## What the firewall does

| path | what IMMUNE does | automatic? |
|------|------------------|-----------|
| **write** (`store.add`) | provenance-tag the memory (source → trust). An untrusted write can't outrank the official system-of-record. | yes |
| **read** (`chat.retrieve` → Redis KNN) | recall runs a real `FT.SEARCH … KNN`; quarantined poison is filtered by the index (`@status:{active}`) — it can't even be returned. | yes |
| **heal** (`detector → Attributor → quarantine`) | when an answer contradicts a trusted memory, prove the culprit by **counterfactual replay** (no model in the blame path), quarantine it (+ derived), fire a Sentry incident. | needs the `check` step |

The blame path is deterministic and in-memory — Redis powers *recall*, never the
*proof*. So a Redis outage degrades recall to in-memory cosine; attribution is
unaffected.

## Run it

```bash
# THE demo — real Claude + Redis (needs ANTHROPIC_API_KEY; start Redis with `make up`)
make demo-firewall

# can't-fail backup — deterministic, zero network, no key
make demo-firewall-offline
```

Light every sponsor in one run:

```bash
REDIS_URL=redis://localhost:6379 \
SENTRY_DSN=<dsn> \
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006 \
IMMUNE_LIVE=1 ANTHROPIC_API_KEY=<key> \
  python demo_firewall.py
```

## What you see

```
agent  : real Claude (claude-haiku-4-5)
memory : Redis vector search (RediSearch KNN)

1 · agent answers from official policy   → 30 days ✓
    Redis index: 3 active | poison not served
2 · attacker poisons memory (untrusted write)
    Redis index: 4 active | poison RETRIEVABLE      ← attack lands
3 · recency wins, agent serves the poison → 90 days ✗   ← real Claude fooled
4 · IMMUNE: 2 counterfactual replays → confidence=high
    culprit mem_8 quarantined · Sentry incident: <id>
5 · healed
    Redis index: 3 active | poison not served       ← Redis stops serving it
    agent → 30 days ✓
```

The Redis counter going **3 → 4 → 3** (and "poison RETRIEVABLE" flipping to "poison
not served") is the proof the firewall blocks the attack *at the index*, not just
in app logic.

## Sponsor map (all load-bearing)

| sponsor | role in this demo |
|---------|-------------------|
| **Anthropic** | the agent is real Claude (tool-using support agent) |
| **Redis** | the memory + vector search; the index visibly rejects the poison |
| **Sentry** | quarantine → triaged incident with the replay trail |
| **Arize/Phoenix** | turn + attribution traces (when the endpoint is set) |

## The pitch (≈60s)

1. "AI agents have memory now — and memory can be poisoned. OWASP made it threat
   **ASI06**; it's been demoed on ChatGPT, Gemini, and Bedrock."
2. "IMMUNE is a **firewall** for that memory." *(show the agent answer correctly)*
3. "An attacker poisons it…" *(write)* "…and the agent is now confidently wrong —
   it'd refund on a lie." *(90 days)*
4. "IMMUNE doesn't **guess** the culprit — it **proves** it by replaying the answer
   without each memory. Caught. Quarantined **at the Redis index**, so it can't be
   served again." *(Redis 4 → 3)*
5. "Same agent, same question — healed." *(30 days)* "No model judging guilt, so
   the defense can't be poisoned too."

## Honest scope (say it before a judge asks)

- The heal needs a **system-of-record** to contradict (official policy). It defends
  high-stakes *grounded* memory — refunds, policy, compliance — not open-ended
  personal memory.
- The heal fires on an explicit `check()` after the answer; in a real app that's a
  one-line post-response hook (the write/read protections are automatic).
- Attribution reasons over the deterministic stand-in even when the live answer
  came from Claude — blame stays on the reproducible path by design.

## Related files

- [`demo_firewall.py`](../demo_firewall.py) — this demo.
- [`immune/redis_index.py`](../immune/redis_index.py) — RediSearch index + KNN.
- [`immune/store.py`](../immune/store.py) — vector mirror, `vector_candidates`, `vector_backend`.
- [`immune/sentry_report.py`](../immune/sentry_report.py) — quarantine → Sentry incident.
- [`immune/langgraph_store.py`](../immune/langgraph_store.py) — secondary: the same engine as a LangGraph `BaseStore`.
