"""LLM/SLM-backed RAG chat service on MongoDB (FastAPI).

MongoDB plays three roles in one database:
  1. document_chunks : knowledge base  (text chunk + embedding vector)
  2. vector store    : Atlas $vectorSearch (HNSW) or local brute-force cosine
  3. sessions        : durable conversation memory (capped history per session)

Endpoints
  GET    /health                 liveness + which backends are configured
  POST   /ingest                 chunk -> embed -> upsert documents
  POST   /chat                   retrieve -> build prompt -> generate -> persist
  GET    /sessions/{session_id}  conversation history
  DELETE /sessions/{session_id}  forget a conversation
  GET    /stats                  collection counts

Based on Appendix A of "NoSQL Databases Using MongoDB" (S. Jagtap), extended
for the mini project: real offline embeddings, SLM default, idempotent ingest,
atomic history updates, Atlas Vector Search path, extractive fallback, tests.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymongo import ASCENDING, MongoClient

from . import embeddings, llm

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat_api")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "llm_chat_app")
VECTOR_SEARCH = os.getenv("VECTOR_SEARCH", "local")      # "local" | "atlas"
ATLAS_INDEX = os.getenv("ATLAS_VECTOR_INDEX", "chunk_vector_index")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "120"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "20"))
TOP_K = int(os.getenv("TOP_K", "3"))
HISTORY_TURNS_IN_PROMPT = int(os.getenv("HISTORY_TURNS_IN_PROMPT", "4"))
HISTORY_CAP = int(os.getenv("HISTORY_CAP", "40"))


# ---------- request / response models ----------
class Document(BaseModel):
    title: str
    content: str


class IngestRequest(BaseModel):
    documents: list[Document]
    chunk_size: Optional[int] = None


class IngestResponse(BaseModel):
    documents: int
    chunks_created: int
    chunks_updated: int


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    top_k: int = Field(default=TOP_K, ge=1, le=10)
    context: Optional[str] = Field(default=None, max_length=4000,
                                   description="Live dashboard readings to ground the answer in the user's own server")


class ChatResponse(BaseModel):
    session_id: str
    response: str
    sources: list[dict]
    backend: str
    latency_ms: float
    retrieval_ms: float


# ---------- database ----------
def create_client() -> MongoClient:
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def ensure_indexes(db) -> None:
    db.document_chunks.create_index([("source_title", ASCENDING), ("chunk_index", ASCENDING)],
                                    unique=True, name="uniq_source_chunk")
    db.sessions.create_index("session_id", unique=True, name="uniq_session")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "client", None) is None:      # tests inject a mongomock client
        app.state.client = create_client()
        app.state.client.admin.command("ping")
        logger.info("Connected to MongoDB at %s", MONGO_URI)
    ensure_indexes(app.state.client[MONGO_DB])
    yield
    app.state.client.close()


app = FastAPI(title="MongoDB RAG Chat (LLM/SLM)", version="2.0.0", lifespan=lifespan)


def db():
    return app.state.client[MONGO_DB]


# ---------- chunking ----------
def chunk_words(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    out = []
    for start in range(0, len(words), step):
        out.append(" ".join(words[start:start + size]))
        if start + size >= len(words):
            break
    return out


# ---------- retrieval ----------
def retrieve(query: str, top_k: int) -> list[dict]:
    qvec = embeddings.embed(query)
    col = db().document_chunks
    if VECTOR_SEARCH == "atlas":
        pipeline = [
            {"$vectorSearch": {"index": ATLAS_INDEX, "path": "embedding", "queryVector": qvec,
                               "numCandidates": max(50, top_k * 20), "limit": top_k}},
            {"$project": {"_id": 0, "text": 1, "source_title": 1, "chunk_index": 1,
                          "score": {"$meta": "vectorSearchScore"}}},
        ]
        hits = list(col.aggregate(pipeline))
    else:
        hits = []
        for d in col.find({}, {"_id": 0, "text": 1, "source_title": 1, "chunk_index": 1, "embedding": 1}):
            d["score"] = embeddings.cosine(qvec, d.pop("embedding"))
            hits.append(d)
        hits.sort(key=lambda h: h["score"], reverse=True)
        hits = hits[:top_k]
    return [{"source": h["source_title"], "chunk": h["chunk_index"],
             "score": round(float(h["score"]), 4), "text": h["text"]} for h in hits]


# ---------- endpoints ----------
@app.get("/health")
def health():
    try:
        db().command("ping")
        mongo = "connected"
    except Exception:
        mongo = "disconnected"
    return {"status": "ok" if mongo == "connected" else "degraded", "mongo": mongo,
            "llm_backend": llm.LLM_BACKEND, "model": {"ollama": llm.OLLAMA_MODEL, "openai": llm.OPENAI_MODEL}.get(llm.LLM_BACKEND, "no model (extractive)"),
            "embedding_backend": embeddings.BACKEND, "vector_search": VECTOR_SEARCH}


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest):
    size = req.chunk_size or CHUNK_SIZE
    col, now = db().document_chunks, datetime.now(timezone.utc)
    created = updated = 0
    for doc in req.documents:
        # one upsert per (title, chunk_index): re-ingesting a document refreshes
        # its chunks instead of duplicating them (idempotent ingest)
        for i, chunk in enumerate(chunk_words(doc.content, size)):
            res = col.update_one(
                {"source_title": doc.title, "chunk_index": i},
                {"$set": {"text": chunk, "embedding": embeddings.embed(chunk),
                          "embedding_backend": embeddings.BACKEND},
                 "$setOnInsert": {"created_at": now}},
                upsert=True)
            created += res.upserted_id is not None
            updated += res.modified_count
    if created + updated == 0 and not col.count_documents({"source_title": {"$in": [d.title for d in req.documents]}}):
        raise HTTPException(400, "No content to ingest")
    return IngestResponse(documents=len(req.documents), chunks_created=created, chunks_updated=updated)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    t0 = time.perf_counter()
    sources = retrieve(req.message, req.top_k)
    t_ret = (time.perf_counter() - t0) * 1000

    session = db().sessions.find_one({"session_id": req.session_id}, {"history": 1})
    history = (session or {}).get("history", [])[-HISTORY_TURNS_IN_PROMPT * 2:]
    history = [{"role": m["role"], "content": m["content"]} for m in history]

    answer, used = llm.generate(req.message, sources, history, req.context)

    now = datetime.now(timezone.utc)
    db().sessions.update_one(
        {"session_id": req.session_id},
        {"$push": {"history": {"$each": [
            {"role": "user", "content": req.message, "ts": now},
            {"role": "assistant", "content": answer, "ts": now,
             "sources": [f"{s['source']}#{s['chunk']}" for s in sources], "backend": used},
        ], "$slice": -HISTORY_CAP}},
         "$set": {"updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True)

    return ChatResponse(session_id=req.session_id, response=answer, sources=sources, backend=used,
                        latency_ms=round((time.perf_counter() - t0) * 1000, 1), retrieval_ms=round(t_ret, 1))


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    s = db().sessions.find_one({"session_id": session_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Session not found")
    return s


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    return {"deleted": db().sessions.delete_one({"session_id": session_id}).deleted_count}


@app.get("/stats")
def stats():
    d = db()
    return {"chunks": d.document_chunks.count_documents({}),
            "sources": len(d.document_chunks.distinct("source_title")),
            "sessions": d.sessions.count_documents({})}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.chat_api:app", host="0.0.0.0", port=8000)
