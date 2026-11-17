"""End-to-end API tests against an in-memory MongoDB (mongomock).

    cd mini-project && pytest -q
"""

import json
import os
from pathlib import Path

import mongomock
import pytest

os.environ["LLM_BACKEND"] = "extractive"
os.environ["EMBEDDING_BACKEND"] = "hash"

from fastapi.testclient import TestClient  # noqa: E402

from app import chat_api, llm  # noqa: E402

KB = json.loads((Path(__file__).resolve().parents[1] / "data/knowledge_base.json").read_text())


@pytest.fixture()
def client():
    llm.LLM_BACKEND = "extractive"
    chat_api.embeddings.BACKEND = "hash"
    chat_api.app.state.client = mongomock.MongoClient()
    with TestClient(chat_api.app) as c:
        yield c
    chat_api.app.state.client = None


def test_health(client):
    body = client.get("/health").json()
    assert body["mongo"] == "connected" and body["embedding_backend"] == "hash"


def test_multi_document_ingest_creates_chunks_for_every_document(client):
    r = client.post("/ingest", json={"documents": KB, "chunk_size": 60}).json()
    assert r["documents"] == len(KB)
    stats = client.get("/stats").json()
    assert stats["sources"] == len(KB)          # every document, not just the first
    assert r["chunks_created"] == stats["chunks"] > len(KB)


def test_reingest_is_idempotent(client):
    client.post("/ingest", json={"documents": KB})
    first = client.get("/stats").json()["chunks"]
    again = client.post("/ingest", json={"documents": KB}).json()
    assert again["chunks_created"] == 0
    assert client.get("/stats").json()["chunks"] == first


def test_chat_retrieves_grounded_source_and_persists_history(client):
    client.post("/ingest", json={"documents": KB, "chunk_size": 60})
    r = client.post("/chat", json={"session_id": "s1", "message": "Why is a timestamp a bad shard key?"}).json()
    assert r["sources"][0]["source"] == "Sharding and Horizontal Scaling"
    assert r["response"].endswith("[1]")
    client.post("/chat", json={"session_id": "s1", "message": "What does mongos do?"})
    hist = client.get("/sessions/s1").json()["history"]
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    assert hist[1]["sources"]


def test_history_is_capped(client, monkeypatch):
    monkeypatch.setattr(chat_api, "HISTORY_CAP", 6)
    client.post("/ingest", json={"documents": KB[:2]})
    for i in range(5):
        client.post("/chat", json={"session_id": "cap", "message": f"question {i}"})
    assert len(client.get("/sessions/cap").json()["history"]) == 6


def test_empty_message_rejected(client):
    assert client.post("/chat", json={"session_id": "x", "message": ""}).status_code == 422


def test_delete_session(client):
    client.post("/ingest", json={"documents": KB[:1]})
    client.post("/chat", json={"session_id": "gone", "message": "hello"})
    assert client.delete("/sessions/gone").json()["deleted"] == 1
    assert client.get("/sessions/gone").status_code == 404
