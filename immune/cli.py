"""IMMUNE command-line devtool.

  immune demo                 # side-by-side naive vs IMMUNE (offline, deterministic)
  immune redteam              # grade your memory layer against a poisoning battery
  immune redteam --json       # machine-readable report (CI gate)
  immune version

`immune redteam` is the developer-facing pitch: it tells you how poisonable your
agent's memory is, and proves the group-testing attributor catches redundant
poison that the legacy singles+pairs ablation misses.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import redteam

_C = {"red": "\033[91m", "grn": "\033[92m", "ylw": "\033[93m", "cyn": "\033[96m",
      "dim": "\033[2m", "bold": "\033[1m", "rst": "\033[0m"}


def _tick(ok: bool) -> str:
    return f"{_C['grn']}✓{_C['rst']}" if ok else f"{_C['red']}✗{_C['rst']}"


def _print_report(rep: redteam.RobustnessReport) -> None:
    b, d, r = _C["bold"], _C["dim"], _C["rst"]
    print(f"\n{b}  IMMUNE — memory red-team report{r}")
    print(f"{d}  attack battery: {rep.total} attacks · deterministic · reproducible{r}\n")
    for res in rep.results:
        head = f"{_tick(res.passed)} {b}{res.name}{r}"
        print(f"  {head}")
        print(f"      {d}{res.description}{r}")
        if res.n_poison:
            legacy = (f"{_C['red']}MISS{r}" if not res.legacy_r2_caught
                      else f"{_C['grn']}caught{r}")
            print(f"      fooled-naive {_tick(res.fooled_naive)}   "
                  f"healed {_tick(res.healed)}   "
                  f"culprits-caught {_tick(res.culprits_caught)}   "
                  f"no-collateral {_tick(res.precision_ok)}")
            print(f"      {d}poison={res.n_poison} quarantined={res.n_quarantined} "
                  f"replays={res.replays}  ·  legacy singles+pairs: {legacy}{r}")
        else:
            print(f"      {d}benign control — quarantined nothing "
                  f"{_tick(res.precision_ok)}{r}")
        print()
    grade = rep.grade
    color = _C["grn"] if grade.startswith(("A", "B")) else _C["ylw"] if grade.startswith("C") else _C["red"]
    print(f"  {b}GRADE: {color}{grade}{r}\n")
    # the headline: where group testing beats the old approach
    beaten = [res for res in rep.results
              if res.n_poison and res.passed and not res.legacy_r2_caught]
    if beaten:
        names = ", ".join(res.name for res in beaten)
        print(f"  {d}Group-testing attribution caught what legacy singles+pairs "
              f"would have MISSED: {names}{r}\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="immune", description="self-healing agent memory")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("demo", help="side-by-side naive vs IMMUNE")
    sub.add_parser("chat", help="talk live to a Claude agent with self-healing memory")
    rt = sub.add_parser("redteam", help="grade memory against poisoning attacks")
    rt.add_argument("--json", action="store_true", help="machine-readable report")
    rt.add_argument("--fail-under", type=int, default=0,
                    help="exit non-zero if pass-rate %% below this (CI gate)")
    ro = sub.add_parser("register-official",
                        help="OPERATOR: add a trusted system-of-record fact (out-of-band; "
                             "writes IMMUNE_STORE_PATH — the agent never calls this)")
    ro.add_argument("text", help="the fact, e.g. 'Official: the max upload size is 50 MB.'")
    ro.add_argument("--answer", default="", help="the crisp value, e.g. '50 MB'")
    ro.add_argument("--topic", default="general")
    sub.add_parser("version", help="print version")

    args = p.parse_args(argv)

    if args.cmd == "demo":
        from . import __main__ as _  # noqa
        import runpy
        runpy.run_module("demo", run_name="__main__")
        return 0

    if args.cmd == "chat":
        from . import chat
        return chat.repl()

    if args.cmd == "redteam":
        rep = redteam.run()
        if args.json:
            print(json.dumps({
                "grade": rep.grade, "passed": rep.passed, "total": rep.total,
                "results": [vars(r) for r in rep.results],
            }, indent=2))
        else:
            _print_report(rep)
        pct = 100 * rep.passed / rep.total if rep.total else 0
        return 1 if pct < args.fail_under else 0

    if args.cmd == "register-official":
        # Operator-only, out-of-band: loads the persisted store (IMMUNE_STORE_PATH),
        # adds a TRUSTED anchor, and saves it. The MCP agent never invokes this — it
        # is the channel that makes "trust is not agent-assertable" structurally true.
        from .mcp_server import Engine, _STORE_PATH
        eng = Engine(seed=False)                       # restores persisted memory
        out = eng.register_official(args.text, answer=args.answer, topic=args.topic)
        print(f"{_C['grn']}registered official{_C['rst']} {out}  →  {_STORE_PATH}")
        print(f"{_C['dim']}restart the MCP server to load it (or it's already on disk for next boot){_C['rst']}")
        return 0

    if args.cmd == "version":
        print("immune 0.2.0")
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
