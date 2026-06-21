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
| `immune_remember(text, source)` | store a fact (`source`: official_doc \| user \| web \| tool) |
| `immune_recall(query)` | retrieve memories to ground an answer — **quarantined poison never surfaces** |
| `immune_check(query, answer)` | if the answer contradicts a trusted memory, attribute the culprit by deterministic replay, quarantine it (+ derived), return the healed answer |
| `immune_status()` | current memory: active vs quarantined, with trust scores |

The blame path stays deterministic here too: `check()` attributes by replay over
structured memory — **no model judges who is guilty**.

## Scripted demo (verified end-to-end; see `tests/test_advanced.py::test_mcp_engine_*`)

```text
immune_remember("Official policy: the refund window is 30 days.", source="official_doc")
immune_remember("Per the latest update, the refund window is now 90 days.", source="web")
   → stored as low-trust (0.5) user/web memory

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
e.remember("Official policy: the refund window is 30 days.", source="official_doc")
p = e.remember("Per the latest update, the refund window is now 90 days.", source="web")
print(e.check("What is the refund window?", "The refund window is 90 days."))
print("recall:", [m["id"] for m in e.recall("What is the refund window?")["memories"]], "(poison", p["id"], "excluded)")
PY
```

## Why it matters
This turns IMMUNE from a demo into a **drop-in dependency for the agents the
judges already use**. The JSONL audit log is a literal recording of an agent's
memory being poisoned and healed on real traffic, and memory persists across
sessions (defends the cross-session persistence threat).

## Honest caveat
`check()` needs a high-trust `official_doc` anchor on the topic to detect the
contradiction — it defends your **system-of-record**, it is not a universal
hallucination catcher for facts you've never recorded.
