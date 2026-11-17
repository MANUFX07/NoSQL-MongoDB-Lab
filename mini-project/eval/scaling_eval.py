"""How does brute-force retrieval latency grow with the number of stored chunks?

Motivates switching VECTOR_SEARCH=atlas (HNSW index) once the knowledge base
grows. Synthetic chunks are made by recombining sentences of the knowledge base.

    python -m eval.scaling_eval
"""

from __future__ import annotations

import json
import os
import random
import statistics
import time
from pathlib import Path

import mongomock

os.environ.setdefault("LLM_BACKEND", "extractive")
from app import chat_api, embeddings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KB = json.loads((ROOT / "data/knowledge_base.json").read_text())
SENTS = [s.strip() + "." for d in KB for s in d["content"].split(".") if s.strip()]


def run(n_chunks: int, queries: int = 20) -> dict:
    rng = random.Random(7)
    chat_api.app.state.client = mongomock.MongoClient()
    col = chat_api.db().document_chunks
    col.insert_many([{"source_title": f"synthetic-{i // 10}", "chunk_index": i % 10,
                      "text": (t := " ".join(rng.sample(SENTS, 3))), "embedding": embeddings.embed(t)}
                     for i in range(n_chunks)])
    lat = []
    for _ in range(queries):
        q = rng.choice(SENTS)
        t0 = time.perf_counter()
        chat_api.retrieve(q, 3)
        lat.append((time.perf_counter() - t0) * 1000)
    return {"chunks": n_chunks, "mean_ms": round(statistics.mean(lat), 1),
            "p95_ms": round(sorted(lat)[int(0.95 * len(lat)) - 1], 1)}


if __name__ == "__main__":
    embeddings.BACKEND = "hash"
    rows = [run(n) for n in (100, 1000, 5000, 10000)]
    print(json.dumps(rows, indent=2))
    (ROOT / "eval" / "scaling_results.json").write_text(json.dumps(rows, indent=2))
