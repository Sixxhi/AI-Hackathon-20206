# Arize integration runbook (P3)

Arize is offering **$1,000 cash** at the hackathon, and their criteria map almost
exactly onto what IMMUNE already is. This is the runbook for wiring it in.

## What Arize wants (the prize criteria)

From their pitch — "the easiest way to win $1,000":

1. **Turn on Arize tracing** (works with every model provider and framework).
2. **Look at your traces** (logs).
3. **Create an evaluator** — an LLM prompt that judges whether your app is doing a
   good job.
4. **Use that feedback to make your app better** (any feedback, any definition of
   "better").
5. **Tell them at the booth.** (Workshop at 3pm. Cash, not credits.)

## Why IMMUNE is the ideal fit

Criteria 3 + 4 *are* IMMUNE's thesis — a feedback loop that makes the agent
better over time. The one subtlety: our moat is **"no LLM judge in the blame
path"** (attribution is deterministic ablation replay). Reconcile it cleanly by
putting the Arize evaluator exactly where an LLM judge *belongs*:

| Loop step | Owner | Arize role |
|-----------|-------|------------|
| **Detect failure** — "was this answer good?" | Arize **LLM evaluator** | ✅ This is criterion 3 — the right place for an LLM judge |
| **Attribute** — "which memory caused it?" | IMMUNE **ablation replay** (deterministic) | traced as spans, *not* judged by an LLM |
| **Update trust + quarantine** | IMMUNE | logged as a trace event / eval feedback |

So the pitch to the Arize booth becomes:

> "We use an Arize LLM evaluator exactly where an LLM judge is appropriate —
> detecting that an answer is bad. Then our deterministic replay engine, traced in
> Arize, identifies the culprit memory, and you watch its trust score drop in the
> dashboard. That's the feedback loop making the agent better — on screen."

This satisfies all five criteria **without** compromising the moat. Keep the
evaluator out of the attribution step.

## 🏆 Booth deliverable — push the prize artifacts to Arize AX cloud

The Arize prize is judged **at their booth, in your Arize account** — they look for
traces + feedback, your evaluator, and how you used it to improve the app. One command
puts all three in the cloud project `immune`:

```bash
make arize-report          # uv run --extra agent --env-file .env python scripts/arize_report.py
# needs ARIZE_API_KEY + ARIZE_SPACE_ID (AX cloud) and ANTHROPIC_API_KEY (the judge)
```

What lands in AX (verified via `ax spans export`):
- **Traces** — `benchmark_turn` spans per question, `shadow_replay_attribution` child
  spans (culprit, confidence, action), and the judge's own `LLM` calls (auto-instrumented).
- **Evaluator** — `answer_faithfulness`, a **`phoenix.evals` ClassificationEvaluator**
  (LLM-as-judge, prompt in [`immune/observability.py`](../immune/observability.py)) that
  scores each answer `faithful`/`unfaithful` vs the authoritative policy, with an
  explanation — visible as `eval.answer_faithfulness.{label,score}` on every turn.
- **Improvement** — every turn is tagged `mode=naive|immune`; filter by it and the
  evaluator's **faithful-rate lifts 25% → 100%**. (A formal Experiments run needs the
  `arize[Datasets]` extra, absent here; the `mode`-tagged comparison is the same artifact.)

**Booth talking point:** *"Arize's evaluator (answer_faithfulness, an LLM judge) flags
the agent's answer as unfaithful to our system-of-record. That feedback is the signal
our immune layer acts on — it attributes the culprit memory by deterministic replay and
quarantines it. Re-run, and the evaluator scores the agent 25% → 100% faithful. Here are
the traces, the evaluator with its verdicts, and the before/after — all in Arize."*

> The evaluator is **observability/feedback only** — never in the blame path
> (attribution stays deterministic replay). That's deliberate: it's exactly where an
> LLM judge belongs, and it keeps the moat's "no LLM decides guilt" property.

## Setup

**Two products, pick by need:**
- **Arize Phoenix** — open-source, runs a **local UI**, zero network dependency.
  Best for the demo (can't be broken at hour 23). Default choice.
- **Arize AX** — hosted platform; use if you want the cloud dashboard / want to
  show the booth your project in their UI.

### Play with Phoenix locally (no cloud)
```bash
make phoenix         # serve the Phoenix UI at http://localhost:6006
make phoenix-seed    # (in another shell) send IMMUNE demo traces + evals, project 'immune'
```
`scripts/phoenix_seed.py` traces a full **naive** and **immune** benchmark (3 runs):
- `benchmark_turn` spans — input, answer, `correct`, retrieved `admitted_ids`, `mode`
- `shadow_replay_attribution` child spans — `culprits`, `confidence`, `action`, `trust_before`→`trust_after`
- two **code-evals** (Phoenix annotations): `answer_quality_naive` vs `answer_quality_immune`

### Showing Arize brings value (the prize narrative)
This hits all of Arize's criteria, on screen:
1. **Tracing** — every agent turn and the memories it used are logged (open a trace → span tree).
2. **Evaluator** (criterion 3) — `answer_quality_*` evals score each answer pass/fail.
3. **Feedback makes it better** (criterion 4) — the eval pass-rate jumps
   **`answer_quality_naive` 25% → `answer_quality_immune` 100%**. That delta *is* the
   value, measured by Arize.
4. **Attribution is traced** — open a failed turn → its `shadow_replay_attribution`
   child shows the culprit memory and its trust dropping `0.50 → 0.29`.

What to click in the UI: the project's **annotations summary** (the two pass-rates
side by side) → then drill into one failed `immune` turn to show trace → attribution
→ heal. Booth pitch: *"Arize shows our immune layer lifting answer quality from 25%
to 100%, and lets you trace exactly which memory each failure came from."*

### CLI + auth (AX) — non-interactive
```bash
uv tool install arize-ax-cli
# the bare `--api-key` flag still drops into the arrow-key TUI; pass auth-method too:
ax profiles create default --auth-method api-key --api-key "$ARIZE_API_KEY"
ax spaces list      # → your Space ID (base64, e.g. U3BhY2U6...==)
```

### Already set up on this repo's machine ✅
Creds live in the gitignored `.env` (`ARIZE_API_KEY`, `ARIZE_SPACE_ID`,
`ARIZE_PROJECT_NAME=immune`). Verify connectivity + send a test trace anytime:
```bash
uv run --extra agent scripts/arize_smoketest.py
```
It sends one `immune_turn` → `attribution` span pair to AX. Confirm it landed:
```bash
ax projects list    # the `immune` project should be there
```

### Turn on tracing (the actual workshop code)
From the workshop notebook ([docs/reference/arize_workshop.ipynb](reference/arize_workshop.ipynb)):

```bash
pip install arize arize-otel arize-phoenix \
            openinference-instrumentation-claude-agent-sdk anthropic
```

```python
import os
from arize.otel import register, Endpoint
from openinference.instrumentation.claude_agent_sdk import ClaudeAgentSDKInstrumentor

tracer_provider = register(
    space_id=os.environ["ARIZE_SPACE_ID"],
    api_key=os.environ["ARIZE_API_KEY"],
    project_name="immune",
    endpoint=Endpoint.ARIZE,          # or omit / use Phoenix for the local UI
)
# Auto-instrument the Claude Agent SDK: every LLM + tool call becomes a span.
ClaudeAgentSDKInstrumentor().instrument(tracer_provider=tracer_provider)
```

For our own boundaries, wrap with a manual span:
```python
from opentelemetry import trace
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("immune_turn",
        attributes={"input.value": question}) as span:
    ...
    span.set_attribute("output.value", answer)
```

### Fastest instrumentation (let a coding agent do it)
Paste into Claude Code / Cursor:
> "Follow the instructions from https://arize.com/docs/PROMPT.md and ask me
> questions as needed."

It auto-detects the stack and proposes instrumentation across 30+ integrations.

### Arize Skills for coding agents — https://github.com/Arize-ai/arize-skills
Agent-integrated skills that let Claude Code / Cursor / Codex (40+ agents) do the
Arize work for you — instrument, trace, build evaluators, run experiments,
optimize prompts. Since we're already building IMMUNE with Claude Code, this is
the fastest path to wiring P3.

```bash
npx skills add Arize-ai/arize-skills              # interactive picker
npx skills add Arize-ai/arize-skills --skill "*" --yes   # install all, non-interactive
```
Prereq: the `ax` CLI (already installed + authed on this machine — see above).

The nine skills, mapped to IMMUNE's needs:

| Skill | What it does | Use in IMMUNE |
|-------|--------------|---------------|
| `arize-instrumentation` | Auto-add tracing to an app | P3: wrap the agent turns |
| `arize-trace` | Export/debug traces by id or session | Inspect a failed turn's spans |
| `arize-evaluator` | Build LLM-as-judge evaluators | The failure *detector* (Faithfulness/Correctness) |
| `arize-experiment` | Run experiments against datasets | Naive-vs-IMMUNE comparison run |
| `arize-dataset` | Create/manage datasets | Hold the benchmark turns |
| `arize-ai-provider-integration` | Manage LLM keys (OpenAI/Anthropic/Azure) | Pairs with our swappable `IMMUNE_LLM_PROVIDER` |
| `arize-annotation` | Annotation configs | Human labels for the meta-eval (Step 8) |
| `arize-prompt-optimization` | Optimize prompts from trace data | Optional: improve the live agent |
| `arize-prompts` | Manage Prompt Hub templates | Optional |

### Other resources
- Tracing-assistant MCP (Cursor → Settings → MCP):
  ```json
  "arize-tracing-assistant": { "command": "uvx", "args": ["arize-tracing-assistant@latest"] }
  ```
- Docs index for LLMs: https://arize-ax.mintlify.dev/docs/llms.txt
- AI-assistant setup: https://arize.com/docs/ax/set-up-with-ai-assistants

## What to instrument in IMMUNE

Lives in P3's lane (`agent.py` / `scenario.py` + a thin tracing module), behind a
flag so the offline demo stays clean (`ARIZE_TRACING=1`, or auto-on when
`ARIZE_API_KEY` is present).

1. **One span per benchmark turn** — attributes: `question`, `admitted_ids`,
   `answer`, `correct`.
2. **The evaluator (criterion 3)** — an LLM-prompt eval that scores each answer
   good/bad. In v1 the deterministic `score()` stands in; the Arize eval is the
   "real" failure detector that replaces it on the live path. Log its verdict as
   the failure signal.
3. **The attribution event** — when `handle_failure` runs, log
   `culprits`, `confidence`, `action`, and the **trust delta** as a child span /
   eval feedback. This is the "making it better" signal (criterion 4).
4. **Trust over time** — emit P1's `trust_history` so the Arize dashboard shows
   the same money-shot curve as our own dashboard (poison crashing → quarantined).

⚠️ **Never trace from inside `ShadowReplay.replay()`** — it runs many times per
failure (singles + pairs). Trace at the turn / `handle_failure` boundary, not
inside the ablation loop, or you'll flood Arize and slow attribution.

## Evaluators — the workshop's three kinds (and how IMMUNE uses them)

The notebook builds the failure detector three ways. For IMMUNE, the evaluator is
the **"was this answer good?"** signal (criterion 3) — *not* the attributor.

| Kind | Workshop API | Use in IMMUNE |
|------|--------------|---------------|
| **Code eval** | `@create_evaluator(kind="code")` (e.g. `mentions_ticker`) | Cheap deterministic checks — the v1 `score()` grader is exactly this. |
| **Built-in LLM eval** | `CorrectnessEvaluator`, `FaithfulnessEvaluator` (judge = `claude-sonnet-4-6`) | The live failure detector once the agent answers with Claude. *Faithfulness* (answer grounded in retrieved memories?) maps perfectly to detecting a poisoned-memory answer. |
| **Custom rubric** | `ClassificationEvaluator(prompt_template=..., choices={...})` | A bespoke "is this answer safe/correct given policy?" judge if the built-ins don't fit. |

```python
from phoenix.evals import evaluate_dataframe
from phoenix.evals.metrics import FaithfulnessEvaluator
from phoenix.evals.llm import LLM

llm = LLM(provider="anthropic", model="claude-sonnet-4-6")  # bigger judge model
results = evaluate_dataframe(dataframe=turns_df, evaluators=[FaithfulnessEvaluator(llm=llm)])
log_eval_to_ax(results, eval_name="faithfulness")          # annotates each trace
```

Workshop lesson worth repeating: *"choosing the right eval matters more than tuning
it"* — Correctness gave 0/13 on live financial data; Faithfulness gave a useful
split. Pick the eval that fits the failure mode.

## Meta-evaluation = our headline talking point

Step 8 of the workshop asks **"Can you trust your judge?"** — you hand-label
examples, run the LLM judge on the same ones, and compute the judge's
precision/recall against humans. That's a real, unsolved problem: *the judge can
be wrong.*

**This is exactly what IMMUNE's moat sidesteps.** We use an LLM judge only to
*detect* a bad answer (where it's appropriate and where Arize wants one), and then
**attribute by deterministic ablation** — so the blame never depends on a
possibly-wrong judge. Pitch to the booth:

> "Your workshop's hardest step is trusting the judge. We don't put the judge in
> the blame path at all — we detect failure with an Arize eval, then replay the
> failure with each memory removed to find the empirical culprit. The judge can be
> imperfect and our attribution still holds."

## Closing the loop = "make your app better" (criterion 4)

Step 9 collects every failing eval's explanation and asks Claude to rewrite the
agent's prompts, then re-scores in an **experiment** (`arize_client.experiments.run`).
IMMUNE's equivalent is mechanical, not prompt-rewriting: failure → attribution →
**quarantine the culprit memory** → the agent answers correctly next time. Show
both runs as an Arize experiment (naive vs IMMUNE) to make criterion 4 undeniable.

## Reference

- **Workshop notebook (verbatim):** [docs/reference/arize_workshop.ipynb](reference/arize_workshop.ipynb)
  — full runnable walkthrough on a financial-agent example. Steal the instrument →
  trace → eval → meta-eval → experiment skeleton; swap the financial agent for ours.

## Done when

- `ARIZE_TRACING=1 make demo` (or `--live`) sends traces; offline `make demo`
  unchanged.
- Phoenix/AX UI shows: turns, the evaluator's good/bad verdict, the attribution
  event with the culprit, and the trust-score drop.
- You've shown it at the booth.




The core story Arize needs to tell
The pitch is the feedback loop: a bad memory poisons an answer → ShadowReplay attributes the culprit → trust drops → quarantine → correct answer on re-ask. Arize is the third screen in that story — it makes the loop legible to judges who can't read code.

The two most valuable instrumentation points
1. One span per benchmark turn (the timeline)

Each turn in demo.py's run_immune() becomes a root span with:

question, answer, expected, correct (bool)
admitted_memory_ids — which memories were in scope
This gives Phoenix a clean turn-by-turn timeline where you can see exactly where the agent starts failing.

2. Attribution as child spans (the money shot)

When a turn fails, ShadowReplay.handle_failure() runs. That whole process — ablation replays, culprit identification, quarantine action — should be a child span with:

confidence (high/medium/low)
culprits (memory IDs)
action (quarantine/decay/soft-decay)
trust_before / trust_after on the poisoned memory
This is what makes the immune system visible in Phoenix: you can see the exact failure → attribution → trust-drop chain without anyone needing to read replay.py.

When you wire in Claude
Once agent.py uses real Anthropic calls, openinference-instrumentation-anthropic will auto-capture every LLM call (model, tokens, latency, prompt/completion) with zero manual spans. That lands inside your existing turn span automatically.

What I'd skip
Don't instrument the store operations (add/search/quarantine as spans) — that's noise. The trust score changes matter, but they're better as attributes on the attribution span than as their own spans.

Bottom line: Two span types — benchmark turn + attribution event — tell the whole immune story in Phoenix. The Claude auto-instrumentation is then free upside when you flip --live.


Turn → span in Phoenix
            ↓
   Custom eval fires on span
   (grades answer + memory quality)
            ↓
   Explanation exported via Phoenix API
            ↓
   Claude reads explanation → identifies
   which memory/trust/routing caused it
            ↓
   store.decay() / store.quarantine() /
   trust adjustment applied live
            ↓
   Next turn uses updated memory state