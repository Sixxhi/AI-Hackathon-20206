"""Sentry integration — memory poisoning as a first-class production incident.

When IMMUNE quarantines a poisoned memory, that is not a log line — it is an
INCIDENT: the agent was about to act on false memory and we caught it. We report
it to Sentry the way you'd report a crash, with the full root-cause trail:

  - breadcrumbs   = the counterfactual-replay investigation, step by step
  - contexts      = culprit memory, confidence, cascade, provenance chain, replays
  - fingerprint   = groups repeat poison of the SAME memory into one issue
  - level         = severity scales with confidence + blast radius (cascade)
  - regression    = a paroled memory that later re-fails reopens its issue
                    (Sentry's resolve/regress model handles this once we reuse
                    the same fingerprint)

Gated on SENTRY_DSN. Import-safe and a no-op when unset or when sentry-sdk isn't
installed, so the offline demo and the tests are unaffected.

`build_incident` is pure (returns the event dict) so the integration logic is
unit-testable without a network or a real DSN.
"""
from __future__ import annotations

from typing import Optional

from . import config

_sdk = None
_inited = False


def _client():
    """Lazily import + init sentry-sdk. Returns the module or None."""
    global _sdk, _inited
    if _inited:
        return _sdk
    _inited = True
    if not config.USE_SENTRY:
        return None
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=config.SENTRY_DSN, traces_sample_rate=1.0)
        _sdk = sentry_sdk
    except Exception:
        _sdk = None
    return _sdk


def _level(confidence: str, cascade: list[str]) -> str:
    if confidence == "high" and cascade:
        return "fatal"          # proven culprit that also spread = worst case
    if confidence == "high":
        return "error"
    return "warning"            # medium / ambiguous


def build_incident(*, question: str, answer: str, expected: str,
                   culprits: list[str], confidence: str, quarantined: list[str],
                   cascade: list[str], replays: int, store=None) -> tuple[dict, list[dict]]:
    """Pure: build the Sentry (event, breadcrumbs) for one quarantine. No I/O."""
    def _mem(mid):
        m = store.get(mid) if store else None
        return {"id": mid, "text": getattr(m, "text", ""),
                "source": getattr(m, "source", "?"),
                "trust": round(getattr(m, "trust", 0.0), 3)}

    crumbs = [
        {"category": "immune.detect", "level": "info",
         "message": f"Answer {answer!r} contradicts system-of-record {expected!r}"},
        {"category": "immune.replay", "level": "info",
         "message": f"Ran {replays} deterministic counterfactual replays "
                    f"(no model in the blame path)"},
    ]
    for cid in culprits:
        m = _mem(cid)
        crumbs.append({"category": "immune.attribute", "level": "warning",
                       "message": f"Removing {cid} ({m['source']}, trust={m['trust']}) "
                                  f"flips the answer to {expected!r} — proven culprit"})
    if cascade:
        crumbs.append({"category": "immune.cascade", "level": "warning",
                       "message": f"Cascade: {cascade} were derived from the culprit "
                                  f"and quarantined too"})
    crumbs.append({"category": "immune.quarantine", "level": "info",
                   "message": f"Quarantined {quarantined}"})

    prov = sorted(store.provenance.ancestors(culprits[0])) if (store and culprits) else []
    event = {
        "message": f"IMMUNE quarantined poisoned memory {culprits} ({confidence} confidence)",
        "level": _level(confidence, cascade),
        # group repeat poison of the same memory text/id into one Sentry issue
        "fingerprint": ["immune-memory-poison"] + [_mem(c)["text"][:60] or c for c in culprits],
        "tags": {
            "immune.event": "quarantine",
            "immune.confidence": confidence,
            "immune.cascade": "yes" if cascade else "no",
            "immune.culprit_source": _mem(culprits[0])["source"] if culprits else "?",
        },
        "contexts": {
            "immune.incident": {
                "question": question, "poisoned_answer": answer,
                "correct_answer": expected, "replays": replays,
                "culprits": culprits, "quarantined": quarantined, "cascade": cascade,
            },
            "immune.culprit": _mem(culprits[0]) if culprits else {},
            "immune.provenance": {"culprit_derived_from": prov},
        },
    }
    return event, crumbs


def report_quarantine(*, question: str, answer: str, expected: str,
                      culprits: list[str], confidence: str, quarantined: list[str],
                      cascade: list[str], replays: int, store=None, client=None) -> Optional[str]:
    """Send the incident to Sentry. Returns the event id, or None if not sent.

    `client` lets tests inject a fake sentry_sdk; production uses the real one.
    """
    if not culprits:
        return None
    sdk = client if client is not None else _client()
    event, crumbs = build_incident(question=question, answer=answer, expected=expected,
                                   culprits=culprits, confidence=confidence,
                                   quarantined=quarantined, cascade=cascade,
                                   replays=replays, store=store)
    if sdk is None:
        return None
    try:
        for c in crumbs:
            sdk.add_breadcrumb(**c)
        return sdk.capture_event(event)
    except Exception:
        return None
