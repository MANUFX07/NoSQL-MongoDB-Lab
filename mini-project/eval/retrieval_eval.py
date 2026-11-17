"""Retrieval evaluation: does the right source come back for each question?

Runs the full ingest + retrieve path of the API against an in-memory MongoDB
(mongomock) for each embedding backend and reports Hit@1, Hit@3, MRR and mean
retrieval latency over data/eval_questions.json.

    python -m eval.retrieval_eval            # from mini-project/
    python -m eval.retrieval_eval --backends hash mock ollama
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import mongomock

os.environ.setdefault("LLM_BACKEND", "extractive")
from app import chat_api, embeddings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KB = json.loads((ROOT / "data/knowledge_base.json").read_text())
QS = json.loads((ROOT / "data/eval_questions.json").read_text())


def run(backend: str, chunk_size: int = 60, top_k: int = 3) -> dict:
    embeddings.BACKEND = backend
    chat_api.app.state.client = mongomock.MongoClient()
    d = chat_api.db()
    chat_api.ensure_indexes(d)
    chat_api.ingest(chat_api.IngestRequest(documents=[chat_api.Document(**x) for x in KB], chunk_size=chunk_size))
    hit1 = hit3 = 0
    rr, lat = [], []
    for item in QS:
        t = time.perf_counter()
        res = chat_api.retrieve(item["q"], top_k)
        lat.append((time.perf_counter() - t) * 1000)
        srcs = [r["source"] for r in res]
        hit1 += srcs[:1] == [item["expected"]]
        hit3 += item["expected"] in srcs
        rr.append(1 / (srcs.index(item["expected"]) + 1) if item["expected"] in srcs else 0.0)
    n = len(QS)
    return {"backend": backend, "chunks": d.document_chunks.count_documents({}), "questions": n,
            "hit@1": round(hit1 / n, 3), "hit@3": round(hit3 / n, 3), "mrr": round(sum(rr) / n, 3),
            "mean_retrieval_ms": round(statistics.mean(lat), 2)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", nargs="+", default=["mock", "hash"])
    args = ap.parse_args()
    rows = [run(b) for b in args.backends]
    print(json.dumps(rows, indent=2))
    out = ROOT / "eval" / "results.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"saved -> {out}")
