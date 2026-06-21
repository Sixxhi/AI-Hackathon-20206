# Demo — what IMMUNE does & how to use it

**IMMUNE is an immune system for AI agent memory.** Agents store long-term
memories and later trust them blindly — so a poisoned, stale, or polluted memory
silently corrupts future answers. IMMUNE traces *which* memory caused a bad
answer (by deterministic replay), drops its trust, **quarantines** repeat
offenders, and **paroles** them if they're later proven safe again.

> 👉 **The headline demo is now the memory firewall** — a real Claude agent on
> Redis vector memory, poisoned and healed live: [FIREWALL.md](FIREWALL.md) /
> `make demo-firewall`. This doc covers the offline side-by-side (`make demo`),
> still the deterministic, can't-fail baseline.

Full concept: [CONCEPT.md](CONCEPT.md). How it's built: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## What the demo proves (the money shot)

Same self-inflicted poison, two agents, side by side:

- **Naive agent** trusts the newest memory → the poison wins → **1/2 correct**.
- **IMMUNE agent** detects the failure, replays it to find the culprit memory,
  quarantines it, re-answers correctly → **2/2 correct** — and later *paroles* the
  memory when the truth legitimately changes.

The poison is **self-generated** (the agent wrongly infers "90 days" from
ambiguous input), not planted by us — so it can't be dismissed as rigged.

---

## Quick start (zero keys, ~2 min)

```bash
make setup      # uv sync (one-time)
make test       # 7 invariants — all pass
make demo       # the side-by-side below
```
No API keys, no network needed. (Full env/integration setup: [SETUP.md](SETUP.md).)

---

## Reading the output

```
NAIVE agent  (no immune layer)
  Q: What's the refund window?  -> '90 days'  (expected '30 days')  WRONG   ← poison wins (recency bias)
  Q: How long does delivery take? -> '3 days'  OK
  ACCURACY: 1/2

IMMUNE agent  (shadow-replay self-healing)
  Q: What's the refund window?  -> '30 days'  OK
     [healed] failure attributed via replay (confidence=high, action=quarantine, culprits=['mem_14'])
  Q: How long does delivery take? -> '3 days'  OK
  ACCURACY: 2/2

MEMORY STATE after healing
  [     active] trust=0.9   official_doc    refund window is 30 days
  [     active] trust=0.9   official_doc    standard delivery is 3 days
  [quarantined] trust=0.29  self_generated  (self-inferred '...90...')   ← POISON, jailed

PAROLE  (truth changed -> offline re-trial -> release)
  Re-trial of quarantined mem_14 against logged failures: NO LONGER FAILS.
  -> PAROLED. Quarantine is not a life sentence.
```

What each block shows:
1. **NAIVE** — without IMMUNE, the fresh poison beats the official policy → wrong answer.
2. **IMMUNE** — the wrong answer is caught; `[healed]` shows attribution **by replay**
   (`culprits=['mem_14']`, `confidence=high`) — no LLM judge in the blame path.
3. **MEMORY STATE** — the poison sits **quarantined** (trust crashed below threshold);
   the legitimate memories are untouched (no autoimmune over-reaction).
4. **PAROLE** — when the truth genuinely changes, the jailed memory is re-tried
   *offline* and released only because it no longer reproduces its failure.

---

## Run modes

| Command | What it does | Needs |
|---------|--------------|-------|
| `make demo` | Offline, deterministic side-by-side (above). The judged demo. | nothing |
| `make test` | Run the 7 invariants that lock the moat. | nothing |
| `IMMUNE_LIVE=1 make demo` | The agent *answers* with real Claude (attribution still deterministic). | `ANTHROPIC_API_KEY` |
| `PHOENIX_COLLECTOR_ENDPOINT=… make demo` | Also streams turns + attribution spans to Arize/Phoenix. | Arize/Phoenix env ([ARIZE.md](ARIZE.md)) |
| `DUMP_STATE=1 make demo` | Writes `.demo_state.pkl` (snapshot + failures) for the dashboard. | nothing |

> **Note on live mode:** with `IMMUNE_LIVE=1`, Claude sees the memories *with their
> trust scores* and tends to pick the trustworthy one outright, so the heal loop
> may not trigger for this scenario. The **offline `make demo` is the canonical,
> hour-23-safe demo** that shows the full heal→quarantine→parole story.

---

## The 60-second pitch (say this over `make demo`)

1. *"Agents trust their memory blindly. Watch the naive agent: a poisoned memory
   wins on recency — it answers **90 days**, which is wrong."* (point at 1/2)
2. *"IMMUNE catches the bad answer and asks: which memory caused it? Not by asking
   another LLM — we **replay the failure with each memory removed**. The one whose
   removal fixes it is the culprit."* (point at `[healed] culprits=['mem_14']`)
3. *"It quarantines the poison, keeps the good memories, and re-answers correctly —
   **2/2**."* (point at MEMORY STATE)
4. *"And it's reversible: when the truth actually changes, the memory is re-tried
   offline and **paroled**. An immune system, not a death sentence."*

Sponsor angles: **Redis** = the memory substrate ([REDIS.md](REDIS.md)), **Arize**
= proving the feedback loop ([ARIZE.md](ARIZE.md)).

---

## Visual dashboard

```bash
make dashboard          # opens http://localhost:8501
```
A dark, interactive web view of the same scenario: the **trust-score timeline**
(poison crashing below the threshold → quarantined), the **naive-vs-IMMUNE
side-by-side**, the **live memory table** (quarantined rows highlighted), and the
**parole** verdict. Drag the **quarantine-threshold slider** to explore. Offline +
deterministic — same engine as `make demo`. (Built with Streamlit; `make lane-frontend`
installs it.)
