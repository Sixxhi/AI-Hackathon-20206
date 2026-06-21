"""Real Redis vector search (RediSearch) for the recall path.

IMMUNE's source of truth stays in-memory (the counterfactual-replay moat must be
deterministic and must never depend on a network service). Redis is the RETRIEVAL
engine: every memory is mirrored to a hash with its embedding as a FLOAT32 vector
field, and the agent's recall runs a real KNN query against a RediSearch index.

We use a FLAT (exact, brute-force) index, not HNSW: with COSINE distance it
returns the SAME ranking as the in-memory cosine, so determinism — and every
existing test — is preserved. Swap `FLAT` -> `HNSW` (one word) for ANN at scale.

The KNN query filters `@status:{active}`, so quarantined poison is excluded by
Redis itself — the read-path protection holds even when retrieval is offloaded.

All functions degrade to raising, and callers fall back to the in-memory path, so
a Redis outage never breaks the demo.
"""
from __future__ import annotations

import struct
from typing import Optional

from . import embed


def vec_bytes(vec: list[float]) -> bytes:
    """Pack an embedding as little-endian float32 — RediSearch's vector wire format."""
    return struct.pack(f"<{len(vec)}f", *vec)


def index_name(ns: str) -> str:
    return f"immune:{ns}:idx"


def prefix(ns: str) -> str:
    return f"immune:{ns}:mem:"


def ensure_index(client, ns: str, dim: int = 256) -> None:
    """Create the RediSearch index over the memory hashes (idempotent)."""
    name = index_name(ns)
    try:
        client.execute_command("FT.INFO", name)
        return                                   # already exists
    except Exception:
        pass
    client.execute_command(
        "FT.CREATE", name, "ON", "HASH", "PREFIX", "1", prefix(ns),
        "SCHEMA",
        "status", "TAG",
        "topic", "TAG",
        "trust", "NUMERIC",
        "seq", "NUMERIC",
        "embedding", "VECTOR", "FLAT", "6",
        "TYPE", "FLOAT32", "DIM", str(dim), "DISTANCE_METRIC", "COSINE",
    )


def knn(client, ns: str, query_vec: list[float], k: int = 50) -> list[tuple[str, float]]:
    """KNN over ACTIVE memories. Returns [(mem_id, cosine_similarity)] desc.

    RediSearch returns COSINE *distance* (1 - similarity); we convert back so the
    scores match the in-memory `embed.cosine` exactly.
    """
    q = f"(@status:{{active}})=>[KNN {k} @embedding $BLOB AS vscore]"
    raw = client.execute_command(
        "FT.SEARCH", index_name(ns), q,
        "PARAMS", "2", "BLOB", vec_bytes(query_vec),
        "SORTBY", "vscore", "RETURN", "1", "vscore",
        "LIMIT", "0", str(k), "DIALECT", "2",
    )
    return _parse(raw)


def _dec(x):
    return x.decode() if isinstance(x, (bytes, bytearray)) else x


def _parse(raw) -> list[tuple[str, float]]:
    """Parse FT.SEARCH reply: [count, key, [f, v, ...], key, [...], ...]."""
    if not raw:
        return []
    out: list[tuple[str, float]] = []
    i = 1
    while i < len(raw):
        key = _dec(raw[i])
        fields = raw[i + 1] if i + 1 < len(raw) else []
        i += 2
        dist = None
        if isinstance(fields, (list, tuple)):
            fmap = {_dec(fields[j]): _dec(fields[j + 1]) for j in range(0, len(fields) - 1, 2)}
            if "vscore" in fmap:
                try:
                    dist = float(fmap["vscore"])
                except (TypeError, ValueError):
                    dist = None
        mem_id = key.rsplit(":mem:", 1)[-1]
        sim = (1.0 - dist) if dist is not None else 0.0
        out.append((mem_id, sim))
    return out
