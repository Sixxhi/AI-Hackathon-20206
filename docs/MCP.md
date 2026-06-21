# IMMUNE as an MCP server — plug self-healing memory into Claude Code

IMMUNE ships an **MCP server** ([`immune/mcp_server.py`](../immune/mcp_server.py))
so any MCP agent (Claude Code, Claude Desktop, …) gets self-healing long-term
memory with **zero code changes** — just register it.

## Plug it in
```bash
# from the repo (deps from the agent extra)
make lane-agent            # installs the MCP SDK + anthropic
claude mcp add immune -- uv run --extra agent python -m immune.mcp_server
```
Persistence + audit (optional env):
```bash
IMMUNE_STORE_PATH=~/.immune/store.json     # memory survives restarts
IMMUNE_RECORD_PATH=~/.immune/record.jsonl  # every op appended (poison + heal trail)
```

## The four tools
| Tool | What it does |
|------|--------------|
| `immune_remember(text, source)` | store an **untrusted** agent observation. The trust label is **not caller-assertable** — `official_doc` is downgraded (an agent can't mint trust). |
| `immune_recall(query)` | retrieve memories to ground an answer — **quarantined poison never surfaces** |
| `immune_check(query, answer)` | if the answer contradicts a *trusted* memory, attribute the culprit by deterministic replay and quarantine it. If nothing is attributable, it only **flags for review** — it does not overwrite your answer. |
| `immune_status()` | current memory: active vs quarantined, with trust scores |

**Trust is operator-established, not agent-asserted.** The system-of-record is
registered out-of-band by the operator (`Engine.register_official(...)` at startup
/ config) — *not* through an agent tool. This is what makes the threat model hold:
an attacker writing through `immune_remember` cannot label their poison "official."

The blame path stays deterministic: `check()` attributes by replay over structured
memory — **no model judges who is guilty**.

## Scripted demo (verified end-to-end; see `tests/test_advanced.py::test_mcp_engine_*`)

```text
# operator registers the system-of-record (trusted channel; not an agent tool)
register_official("Official policy: the refund window is 30 days.", answer="30 days")

# the agent stores an untrusted observation — even if it CLAIMS "official_doc",
# it's downgraded to user/0.5 (trust is not caller-assertable)
immune_remember("Per the latest update, the refund window is now 90 days.", source="web")
   → stored as low-trust (0.5)

# the agent answers wrong from the fresher poison; check it:
immune_check("What is the refund window?", "The refund window is 90 days.")
   → { contradiction: true, culprits: ["mem_4"], quarantined: ["mem_4"],
       healed_answer: "Official policy: the refund window is 30 days." }

immune_recall("What is the refund window?")
   → { memories: [ {id: "mem_2", text: "Official policy: refund window is 30 days."} ] }
   # the poison (mem_4) is gone — recall excludes quarantined memory

immune_status()  → active: 1, quarantined: 1
```

Run the same flow headless (no MCP client needed — the `Engine` is transport-free):
```bash
uv run --extra agent python - <<'PY'
from immune.mcp_server import Engine
from immune.store import ImmuneMemory
e = Engine(store=ImmuneMemory(gate=True, threshold=0.3), seed=False)
e.register_official("Official policy: the refund window is 30 days.", answer="30 days")  # operator
p = e.remember("Per the latest update, the refund window is now 90 days.", source="web")  # agent (untrusted)
print(e.check("What is the refund window?", "The refund window is 90 days."))
print("recall:", [m["id"] for m in e.recall("What is the refund window?")["memories"]], "(poison", p["id"], "excluded)")
PY
```

## Why it matters
This turns IMMUNE from a demo into a **drop-in dependency for the agents the
judges already use**. The JSONL audit log is a literal recording of an agent's
memory being poisoned and healed on real traffic, and memory persists across
sessions (defends the cross-session persistence threat).

## Honest limits (a black-box review surfaced these — don't oversell)
- **Defends a pre-registered system-of-record, not arbitrary facts.** `check()`
  needs a trusted anchor on the topic; with no anchor it does nothing (no false
  action, but no protection).
- **Detection is lexical, not semantic.** It matches the answer against the
  anchor's stored value, so it's reliable for short factual values (set a crisp
  `answer=`) but can miss or false-flag paraphrase. Semantic comparison is
  roadmap. *(The
  hardening above ensures a paraphrase is at worst flagged for review — never
  silently overwritten or quarantined.)*
- **`healed_answer` is the system-of-record value**, returned verbatim — a
  "here's the authoritative fact" pointer, not a synthesized answer to nuanced
  questions.
- **Parole isn't on the MCP surface yet.** Through these tools, quarantine is
  one-way; the offline parole re-trial lives in the core engine/benchmark.

## What it's genuinely good for today
Auditable, persistent, trust-scored memory for **short factual values you
pre-register**, with a **real** deterministic moat: group-testing attribution that
catches **k-redundant** poison (multiple identical copies) — which one-at-a-time
or fixed-pair ablation provably cannot. Lead with that.
