"""Embedding backends for the chat application.

Three interchangeable backends, selected with EMBEDDING_BACKEND:

  hash     (default) Offline feature-hashing embedder. Tokenises text into
           unigrams + bigrams, hashes each token into a fixed-size vector
           (signed hashing trick), applies sub-linear TF weighting and L2
           normalisation. No model download, no API key, and - unlike the
           textbook's md5 "mock" embedder - texts that share words really do
           end up close together, so retrieval quality is meaningful.
  ollama   Real neural embeddings from a local Ollama server
           (e.g. nomic-embed-text, all-minilm).
  mock     The original Appendix A md5-seeded random vector. Kept only as a
           baseline for the retrieval evaluation in eval/retrieval_eval.py.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import re

DIM = int(os.getenv("EMBEDDING_DIM", "384"))
BACKEND = os.getenv("EMBEDDING_BACKEND", "hash")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

_STOPWORDS = set(
    "a an the and or of to in on for with by is are was were be been it its this that "
    "as at from which what how why when who does do can i you we they he she use used "
    "using into than then there their about".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9$]+")


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def tokenize(text: str) -> list[str]:
    words = [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOPWORDS]
    # light stemming so "replicas"/"replica", "indexes"/"index" match
    words = [re.sub(r"(es|s)$", "", w) if len(w) > 4 else w for w in words]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def hash_embed(text: str, dim: int = DIM) -> list[float]:
    counts: dict[str, int] = {}
    for tok in tokenize(text):
        counts[tok] = counts.get(tok, 0) + 1
    vec = [0.0] * dim
    for tok, c in counts.items():
        h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
        sign = 1.0 if (h >> 63) & 1 else -1.0
        vec[h % dim] += sign * (1.0 + math.log(c))
    return _normalise(vec)


def mock_embed(text: str, dim: int = DIM) -> list[float]:
    rng = random.Random(hashlib.md5(text.encode()).hexdigest())
    return _normalise([rng.gauss(0, 1) for _ in range(dim)])


def ollama_embed(text: str) -> list[float]:
    import requests

    r = requests.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    r.raise_for_status()
    return _normalise(r.json()["embedding"])


def embed(text: str, backend: str | None = None) -> list[float]:
    backend = backend or BACKEND
    if backend == "ollama":
        return ollama_embed(text)
    if backend == "mock":
        return mock_embed(text)
    return hash_embed(text)


def cosine(a: list[float], b: list[float]) -> float:
    """Dot product == cosine similarity because every vector is unit length."""
    return sum(x * y for x, y in zip(a, b))
