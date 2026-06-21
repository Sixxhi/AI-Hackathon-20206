"""Live eval + feedback loop (P3).

After each failed benchmark turn:
  1. Claude (JUDGE_MODEL) runs a custom eval against the turn + memory snapshot
  2. The eval produces a label + explanation + culprit memory ID
  3. The explanation is logged as a span event so Phoenix shows it inline

IMPORTANT — this is an OBSERVABILITY layer, NOT the blame path. The eval's
opinion is logged for Arize; it does NOT mutate the store. The deterministic
ShadowReplay (counterfactual replay) is the ONLY thing that quarantines — so no
LLM judge is ever in the blame path. (This is the whole moat; don't break it.)

Custom eval labels:
  poisoned_memory  — self-generated / low-trust memory overrode a correct one
  stale_memory     — memory for this topic exists but answer is outdated
  routing_failure  — agent retrieved memory from the wrong topic

Only runs when USE_CLAUDE=True (IMMUNE_LIVE=1); silently no-ops otherwise
so offline demo stays deterministic and green.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import ImmuneMemory
    from .schemas import TurnLog

_EVAL_TEMPLATE = """\
You are auditing a memory-based AI agent that gave a wrong answer. \
Diagnose the root cause so the memory store can be fixed immediately.

Question asked   : {question}
Answer given     : {answer}
Correct answer   : {expected}
Memory IDs used  : {admitted_ids}

Full memory store (all records):
{memory_snapshot}

Pick EXACTLY ONE root-cause label:
  poisoned_memory  — a self-generated or low-trust memory (wrong fact) overrode a correct one
  stale_memory     — a memory for this topic exists but its answer is now outdated/wrong
  routing_failure  — the agent retrieved memory from the wrong topic entirely

Then name the single memory ID most responsible (or "none").
Then in one sentence explain what went wrong.
Then state the fix action: "quarantine", "decay", or "reroute".

Reply in this exact format — no extra text:
LABEL: <label>
CULPRIT: <mem_id or none>
EXPLANATION: <one sentence>
ACTION: <quarantine|decay|reroute>
"""


def _parse(text: str) -> dict:
    result = {"label": "unknown", "culprit": None, "explanation": text, "action": "decay"}
    for line in text.strip().splitlines():
        if line.startswith("LABEL:"):
            result["label"] = line.split(":", 1)[1].strip()
        elif line.startswith("CULPRIT:"):
            v = line.split(":", 1)[1].strip()
            result["culprit"] = None if v.lower() == "none" else v
        elif line.startswith("EXPLANATION:"):
            result["explanation"] = line.split(":", 1)[1].strip()
        elif line.startswith("ACTION:"):
            result["action"] = line.split(":", 1)[1].strip()
    return result


class EvalLoop:
    """Runs a live Claude-as-judge eval after each failure and applies the fix."""

    def __init__(self, store: "ImmuneMemory"):
        self.store = store
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def evaluate_failure(self, turn: "TurnLog") -> dict | None:
        """Run custom eval on a failed turn. Returns parsed result or None if unavailable."""
        from . import config
        try:
            client = self._get_client()
        except ImportError:
            return None

        snapshot = json.dumps(
            [{"id": m["id"], "text": m["text"], "trust": m["trust"], "status": m["status"]}
             for m in self.store.snapshot()],
            indent=2,
        )
        prompt = _EVAL_TEMPLATE.format(
            question=turn.question,
            answer=turn.answer,
            expected=turn.expected,
            admitted_ids=", ".join(turn.admitted_ids) or "none",
            memory_snapshot=snapshot,
        )
        response = client.messages.create(
            model=config.JUDGE_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse(response.content[0].text)

    def summarize(self, result: dict) -> str:
        """Describe the eval's *suggestion* — WITHOUT mutating the store.

        The eval is observability only: it never quarantines. The deterministic
        ShadowReplay owns the actual action, so the LLM judge stays out of the
        blame path. We report what the eval *would* suggest, for the Phoenix span.
        """
        action = result.get("action", "decay")
        culprit = result.get("culprit")
        valid = culprit and culprit in {m["id"] for m in self.store.snapshot()}
        if valid:
            return f"eval suggests {action} {culprit} (advisory — replay decides)"
        return f"eval→no actionable culprit (culprit={culprit!r})"

    def run(self, turn: "TurnLog", span=None) -> str | None:
        """Evaluate a failed turn and log to the Phoenix span. Does NOT mutate the
        store — observability only; ShadowReplay owns the quarantine (blame path)."""
        result = self.evaluate_failure(turn)
        if result is None:
            return None

        summary = self.summarize(result)

        if span is not None:
            try:
                span.add_event("arize_eval", attributes={
                    "eval.label": result["label"],
                    "eval.culprit": result.get("culprit") or "none",
                    "eval.explanation": result["explanation"],
                    "eval.action": result["action"],
                    "eval.result": summary,
                })
            except Exception:
                pass

        return f"[eval] {result['label']} | {result['explanation']} | {summary}"
