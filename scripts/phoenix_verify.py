"""Verify Phoenix 'immune' project has all expected span fields + evals.

Usage:  uv run --extra agent python scripts/phoenix_verify.py
"""
from __future__ import annotations

import json
import os
import sys

ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
PROJECT = os.getenv("ARIZE_PROJECT_NAME", "immune")

TURN_ATTRS = {
    "input.value", "output.value", "expected", "correct", "mode",
    "admitted_ids", "admitted_memories",
}
TURN_HEAL_ATTRS = {"healed_answer", "healed_correct"}
ATTR_ATTRS = {
    "confidence", "action", "culprits", "culprit_memories",
    "trust_before", "trust_after",
}
EVAL_NAMES = {"answer_quality_naive", "answer_quality_immune"}


def _attrs(row) -> dict:
    return {k.replace("attributes.", ""): v for k, v in row.items()
            if k.startswith("attributes.") and v is not None and str(v) != "nan"}


def main() -> int:
    try:
        from phoenix.client import Client
        import pandas as pd
        import httpx
    except ImportError:
        sys.exit("Install agent extras:  uv sync --extra agent")

    client = Client(base_url=ENDPOINT)
    names = {p["name"] for p in client.projects.list()}
    if PROJECT not in names:
        print(f"FAIL: project '{PROJECT}' not found at {ENDPOINT}")
        return 1

    df = client.spans.get_spans_dataframe(project_name=PROJECT, limit=5000)
    if df.empty:
        print(f"FAIL: no spans in project '{PROJECT}'")
        return 1

    turns = df[df["name"] == "benchmark_turn"]
    attrs = df[df["name"] == "shadow_replay_attribution"]
    errors: list[str] = []

    # --- turn spans ---
    for mode in ("naive", "immune"):
        subset = turns[turns["attributes.mode"] == mode]
        if subset.empty:
            errors.append(f"no benchmark_turn spans with mode={mode}")
            continue
        sample = _attrs(subset.iloc[0])
        missing = TURN_ATTRS - set(sample)
        if missing:
            errors.append(f"benchmark_turn ({mode}) missing: {sorted(missing)}")

    # admitted_memories must parse as JSON with text field
    immune_fails = turns[(turns["attributes.mode"] == "immune") & (turns["attributes.correct"] == False)]
    if immune_fails.empty:
        errors.append("no immune failure turns (expected at least warranty/refund heals)")
    else:
        row = immune_fails.iloc[0]
        a = _attrs(row)
        missing_heal = TURN_HEAL_ATTRS - set(a)
        if missing_heal:
            errors.append(f"immune failure turn missing heal attrs: {sorted(missing_heal)}")
        try:
            mems = json.loads(a["admitted_memories"])
            if not mems or "text" not in mems[0]:
                errors.append("admitted_memories JSON missing text field")
        except (KeyError, json.JSONDecodeError) as e:
            errors.append(f"admitted_memories invalid: {e}")

    # --- attribution spans ---
    if attrs.empty:
        errors.append("no shadow_replay_attribution spans")
    else:
        a = _attrs(attrs.iloc[0])
        for key in ("confidence", "action", "culprits", "culprit_memories"):
            if key not in a:
                errors.append(f"attribution span missing {key}")
        if "trust_before" not in a and not any(k.startswith("trust_before") for k in a):
            # phoenix may flatten or nest — check nested dict keys
            if "trust_before" not in a:
                tb = a.get("trust_before")
                if tb is None and not any("trust_before" in str(k) for k in a):
                    errors.append("attribution span missing trust_before")
        try:
            culprits = json.loads(a.get("culprit_memories", "[]"))
            if not culprits:
                errors.append("culprit_memories empty")
            elif culprits[0].get("status") != "quarantined":
                errors.append("culprit_memories should show status=quarantined")
        except json.JSONDecodeError:
            errors.append("culprit_memories not valid JSON")

    # --- eval annotations ---
    pid = next(p["id"] for p in client.projects.list() if p["name"] == PROJECT)
    q = """
    query ($pid: ID!) {
      node(id: $pid) {
        ... on Project { spanAnnotationNames }
      }
    }
    """
    r = httpx.post(f"{ENDPOINT}/graphql", json={"query": q, "variables": {"pid": pid}})
    ann_names = set(r.json()["data"]["node"]["spanAnnotationNames"])
    missing_evals = EVAL_NAMES - ann_names
    if missing_evals:
        errors.append(f"missing eval annotations: {sorted(missing_evals)}")

    # --- summary ---
    n_turns = len(turns)
    n_attr = len(attrs)
    n_naive = len(turns[turns["attributes.mode"] == "naive"])
    n_immune = len(turns[turns["attributes.mode"] == "immune"])

    print(f"Project '{PROJECT}' @ {ENDPOINT}")
    print(f"  spans: {n_turns} benchmark_turn, {n_attr} shadow_replay_attribution")
    print(f"  modes: {n_naive} naive, {n_immune} immune")
    print(f"  eval annotations: {sorted(ann_names & EVAL_NAMES)}")

    if errors:
        print("\nISSUES:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    # example trace for user
    if not immune_fails.empty:
        tid = immune_fails.iloc[0]["context.trace_id"]
        print(f"\nOK — all expected fields present.")
        print(f"  Demo trace: {ENDPOINT}/projects/{pid}/traces/{tid}")
    else:
        print("\nOK — all expected fields present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
