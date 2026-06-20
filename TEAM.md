# Team onboarding — start coding in 2 minutes

## Everyone, first thing
Install uv once (`curl -LsSf https://astral.sh/uv/install.sh | sh`), then:
```bash
git clone <repo> && cd AI-Hackathon-20206
git checkout immune-v1
make setup              # uv sync — identical deps for all 4 of us (uv.lock)
make test && make demo  # confirm green before you touch anything
cp .env.example .env    # fill only your lane's keys
```
`immune` installs as an editable package, so `import immune` works from any file.
Run things with `uv run <cmd>` (no manual activate needed). The committed
`uv.lock` means everyone gets byte-identical versions — no env drift at hour 12.

## Branch per lane (avoid collisions)
```bash
git checkout immune-v1
git checkout -b lane/<infra|moat|agent|frontend>
# ... work, commit small ...
# open PR into immune-v1, not main
```
Integrate into `immune-v1`. Keep `main` clean for final submission.

## Lanes — own your files, touch nothing else

| You | Lane | Own these files | First task | Extra deps |
|-----|------|-----------------|------------|------------|
| **P1** | Shadow-replay **moat** | `immune/replay.py` | harden attribution (subset>2 cost guard), expose `replay.failed_log` for the dashboard | — |
| **P2** | Memory + infra | `immune/store.py`, `immune/schemas.py` | swap in-memory → Redis vector search behind the SAME `search/add` surface; fire Sentry on `quarantine()` | `make lane-infra` |
| **P3** | Agent + eval | `immune/agent.py`, `immune/scenario.py` | replace mock `answer()`/`score()` with Claude; wire benchmark through Arize Phoenix for the accuracy number | `make lane-agent` |
| **P4** | Frontend + demo | new `dashboard/` | read `store.snapshot()` + `replay.failed_log` → trust-timeline chart + side-by-side terminals + red "QUARANTINED" event | — |

## The contracts — DO NOT change without telling everyone
`immune/schemas.py`: `MemoryRecord`, `TurnLog`, and `ShadowReplay.replay(question, expected, exclude)`.
Everyone codes against these. Change one → message the team first.

## Integration checkpoint
**Hour 12 = hard merge.** If P1+P2+P3 aren't talking by then, cut parole (keep
attribution + quarantine) and ship the smaller win. Protect the side-by-side demo above all.

## Golden rule
Whatever we cut, the **before/after side-by-side stays**. It IS the pitch.
Keep `make demo` green at every merge.
