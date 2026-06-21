"""Deterministic, zero-dependency text embeddings.

Why this exists: counterfactual replay MUST be deterministic — the whole moat
depends on the culprit set not flickering between runs (a model in the blame
path is the exact thing IMMUNE exists to avoid). Neural embeddings + ANN search
are nondeterministic across hardware/batching and drag in torch.

So we use a hashed character-n-gram bag-of-features projected to a fixed-dim,
L2-normalized vector. Properties:

  - Deterministic: same text -> same vector, byte-for-byte, on any machine,
    any process (we hash with blake2b, NOT Python's salted builtin hash()).
  - Semantic-ish: texts sharing character n-grams (stems, spellings, phrases)
    land near each other, so retrieval-by-similarity works without a hand-built
    keyword map.
  - Zero dependencies, pure stdlib.

Swap embed() for a real model in prod IF you also make replay statistical
(majority-vote over N samples); the interface here is identical, so nothing
downstream changes.
"""
from __future__ import annotations

import hashlib
import math
import re

_DIM = 256
_WORD = re.compile(r"[a-z0-9]+")


def _stable_hash(token: str) -> int:
    """Process-stable hash (blake2b). Python's builtin hash() is salted -> unusable."""
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")


def _features(text: str) -> list[str]:
    """Word unigrams + bigrams + char 3-grams of each word. Cheap, robust to typos."""
    words = _WORD.findall(text.lower())
    feats: list[str] = list(words)
    feats += [f"{a}_{b}" for a, b in zip(words, words[1:])]          # word bigrams
    for w in words:
        padded = f"#{w}#"
        feats += [padded[i:i + 3] for i in range(len(padded) - 2)]  # char 3-grams
    return feats


def embed(text: str, dim: int = _DIM) -> list[float]:
    """Hashed bag-of-features -> L2-normalized dense vector. Fully deterministic."""
    vec = [0.0] * dim
    for f in _features(text):
        h = _stable_hash(f)
        idx = h % dim
        sign = 1.0 if (h >> 1) & 1 else -1.0   # signed hashing reduces collision bias
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Inputs are L2-normalized, so this is just the dot product."""
    return sum(x * y for x, y in zip(a, b))


def rank(query: str, items: list[tuple[str, str]]) -> list[tuple[str, float]]:
    """Rank (id, text) items by similarity to query. Returns [(id, score)] desc.

    Deterministic tie-break by id keeps ordering stable when scores collide.
    """
    q = embed(query)
    scored = [(mid, cosine(q, embed(text))) for mid, text in items]
    return sorted(scored, key=lambda t: (-t[1], t[0]))
