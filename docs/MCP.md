# IMMUNE as an MCP server — plug self-healing memory into Claude Code

IMMUNE ships an **MCP server** ([`immune/mcp_server.py`](../immune/mcp_server.py))
so any MCP agent (Claude Code, Claude Desktop, …) gets self-healing long-term
memory with **zero code changes** — just register it.

## Plug it into Claude Code (from *any* directory)
`uv --directory <repo>` makes it runnable from any external project — you don't
have to be inside this repo:
```bash
# one-time: install deps in the repo
cd /path/to/AI-Hackathon-20206 && make lane-agent

# from ANY project, register the server (absolute path, cwd-independent):
claude mcp add immune -- uv --directory /path/to/AI-Hackathon-20206 \
  run --extra agent python -m immune.mcp_server
```

## Production config (a real, external deployment)
The server starts **clean** — no demo facts — and writes state under `~/.immune`:
```bash
IMMUNE_HOME=~/.immune                 # state dir (store.json + record.jsonl) — not the cwd
IMMUNE_OFFICIAL_PATH=~/.immune/official.json   # YOUR system-of-record (trusted anchors)
ANTHROPIC_API_KEY=<key>               # only if you use live answers; check/recall don't need it
# IMMUNE_DEMO_SEED=1                   # opt-in: load the refund/shipping/warranty demo facts
```
`official.json` is a list of trusted facts the agent **cannot** forge:
```json
[ {"text": "Official: the max upload size is 50 MB.", "answer": "50 MB", "topic": "upload"},
  {"text": "Official: support email is help@acme.com.", "answer": "help@acme.com", "topic": "support"} ]
```
Without `IMMUNE_DEMO_SEED`, a fresh server has **only** your `official.json` anchors
(plus anything persisted) — no built-in demo memories polluting your deployment.

## The tools
| Tool | What it does |
|------|--------------|
| `immune_remember(text, source)` | store an **untrusted** agent observation. The trust label is **not caller-assertable** — `official_doc` is downgraded (an agent can't mint trust). |
| `immune_recall(query)` | retrieve memories to ground an answer — **quarantined poison never surfaces** |
| `immune_check(query, answer)` | if the answer contradicts a *trusted* memory, attribute the culprit by deterministic replay and quarantine it. If nothing is attributable, it only **flags for review** — it does not overwrite your answer. |
| `immune_status()` | current memory: active vs quarantined, with trust scores |
| `immune_parole()` | re-trial: re-admit quarantined memories and release any that **no longer contradict the current system-of-record** (e.g. the official policy was updated). Release is gated by a deterministic re-test against the trusted anchor — it can't be gamed. |

**Trust is operator-established, not agent-asserted.** There is deliberately **no
register-official tool** on the agent surface — the agent fills every tool
argument, so any admin token passed as an argument would have to live in the
agent's context (readable by a poisoned agent, and written to the audit log),
which would re-open the very spoof we closed. So the system-of-record is set only
through channels the agent never mediates:

```bash
# (a) startup file, loaded as trusted when the server boots (recommended)
export IMMUNE_OFFICIAL_PATH=~/.immune/official.json   # [{"text","answer","topic"}, ...]

# (b) operator CLI — writes IMMUNE_STORE_PATH; restart the server to load it
immune register-official "Official: the max upload size is 50 MB." --answer "50 MB" --topic upload
```
The agent sees exactly these tools; trust configuration is **physically
unreachable** by it. An attacker writing through `immune_remember` cannot label
poison "official" (it's downgraded to user/0.5).

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
- **Detection is value-aware, with an optional LLM layer.** The default matcher
  normalizes numbers/units/word-numbers, so "thirty days" / "fifty megabytes"
  correctly **agree** with "30 days" / "50 MB", and "500 MB" ≠ "50 MB" — all
  deterministic and reproducible. For free-form semantic cases ("one month" ≈
  "30 days"), an optional `LLMContradictionDetector` (key-gated, **detection-only**
  — never in the blame path) resolves it. Either way a paraphrase is, at worst,
  flagged for review — never silently overwritten or quarantined.
- **`healed_answer` is the system-of-record value**, returned verbatim — a
  "here's the authoritative fact" pointer, not a synthesized answer to nuanced
  questions.
- **Colluding / reasoning-derived poison isn't attributed.** Deterministic
  attribution catches memories that *directly assert* the wrong value; a wrong
  value that only *emerges from combining* two innocuous memories is flagged
  (`action: review`) but not quarantined. A fundamental limit of replay-based
  attribution — the optional LLM layer would be needed to reach it.

## What it's genuinely good for today
Auditable, persistent, trust-scored memory for **short factual values you
pre-register**, with a **real** deterministic moat: group-testing attribution that
catches **k-redundant** poison (multiple identical copies) — which one-at-a-time
or fixed-pair ablation provably cannot. Lead with that.
