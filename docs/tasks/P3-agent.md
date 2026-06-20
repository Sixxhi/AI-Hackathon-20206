# P3 — Agent + eval (Claude + Arize)

**Owns:** [`immune/agent.py`](../../immune/agent.py),
[`immune/scenario.py`](../../immune/scenario.py).
Make the agent real (Claude) and prove the loop in Arize — both **behind flags**,
mock stays default. Setup + key facts: [../ARIZE.md](../ARIZE.md). Provider/model/
keys are already swappable via [config.py](../../immune/config.py).

> ⚠️ Claude is for the **live answer**, not the blame path. Keep `score()` (the
> grader) and `replay()` deterministic — never call an LLM inside replay.

---

### P3-1 · 🔴 must · ~1 h
## Claude-backed `answer()` behind `USE_LLM`
**Steps**
- When `config.USE_LLM`, `answer()` synthesizes from retrieved memories via
  `anthropic` (model `config.AGENT_MODEL`); else the current mock. Still return
  `(answer, admitted_ids)`.
- Optional: route topic via Claude too; keep the keyword router as fallback.

**Done when** `make demo` (no key) is unchanged; with `ANTHROPIC_API_KEY` set the
agent answers via Claude and the loop still attributes + quarantines.

---

### P3-2 · 🔴 must · ~1 h
## Arize tracing — one span per turn
Mirror [`scripts/arize_smoketest.py`](../../scripts/arize_smoketest.py) (already
verified end-to-end).

**Steps**
- When `config.USE_ARIZE`, `register(space_id, api_key, project_name="immune")`
  once at startup.
- Wrap each benchmark turn in an `immune_turn` span with attributes
  `input.value`, `output.value`, `immune.correct`, `immune.admitted_ids`.
- ⚠️ Trace at the **turn boundary**, never inside `replay()` (it runs many times).

**Done when** running the demo with Arize env set populates the `immune` project
with one span per turn; offline demo unchanged.

---

### P3-3 · 🟡 should · ~45 min · dep: P3-2
## Trace the attribution event
Log P1's `events` (culprits, confidence, action, trust_delta) as a child span on
the failed turn.

**Done when** a failed turn in Arize shows the attribution + the trust drop.

---

### P3-4 · 🟡 should · ~1 h · dep: P3-2
## LLM evaluator as the failure detector (Arize criterion 3)
Use `phoenix.evals` (`FaithfulnessEvaluator` / `CorrectnessEvaluator`, judge =
`config.JUDGE_MODEL`) to score answers, logged to Arize. This is the "create an
evaluator" prize requirement — and it sits at *detect failure*, not *attribute*.
See [../ARIZE.md](../ARIZE.md#evaluators--the-workshops-three-kinds-and-how-immune-uses-them).

**Done when** answers carry a Faithfulness/Correctness eval in the Arize UI; the
deterministic `score()` still drives the offline demo.

---

### P3-5 · 🟢 nice · ~1 h
## Second scenario: auth-middleware
Add a security-flavored scenario to [scenario.py](../../immune/scenario.py)
("internal endpoints don't need auth" poison → failed policy check → quarantine).
Better track fit; keep the refund scenario as the default safe demo.

**Done when** a flag/arg selects the scenario; both run green.

---

### P3-6 · 🟢 nice · ~45 min · dep: P3-4
## Experiment: naive vs IMMUNE
Run an Arize experiment (`arize_client.experiments.run`) over the benchmark for
both modes to make "made it better" undeniable. Pattern in the workshop notebook
([../reference/arize_workshop.ipynb](../reference/arize_workshop.ipynb), Step 9).

**Done when** the experiment shows IMMUNE's accuracy > naive in the Arize UI.
