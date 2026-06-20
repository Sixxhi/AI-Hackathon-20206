# Task board

One file per person. Grab your file, work top-down, tick the boxes. Tasks are
**tracer-bullet vertical slices** — each is small, end-to-end, and **must keep
`make demo` green** when merged.

| File | Lane | Owns |
|------|------|------|
| [P1-moat.md](P1-moat.md) | Shadow-replay moat | `immune/replay.py` |
| [P2-infra.md](P2-infra.md) | Memory + infra | `immune/store.py`, `immune/schemas.py` |
| [P3-agent.md](P3-agent.md) | Agent + eval | `immune/agent.py`, `immune/scenario.py` |
| [P4-frontend.md](P4-frontend.md) | Frontend + demo | `dashboard/` |

## How to read a task
Each task has: **ID** · priority (🔴 must / 🟡 should / 🟢 nice) · estimate ·
dependencies · steps · **Done when** (the acceptance check). Work 🔴 first.

## The one cross-lane dependency
**P4 is blocked on [P1-1](P1-moat.md#p1-1--emit-trust_history-)** (the trust
timeline for the money-shot chart). So **P1 does P1-1 first**, in the first hour.
Everything else runs in parallel — the locked contracts in
[schemas.py](../../immune/schemas.py) are the firewall.

## Rules (non-negotiable)
1. `make demo` green at every merge — integrations hide behind flags.
2. No integration in the replay/attribution path — keep it deterministic.
3. Don't edit `schemas.py` without announcing (P2 owns it; frozen after hour 1).
4. Branch per lane (`lane/<moat|infra|agent|frontend>`), merge into `immune-v1`.

See [../PLAN.md](../PLAN.md) for strategy/timeline and [../SETUP.md](../SETUP.md)
to get your environment running.
