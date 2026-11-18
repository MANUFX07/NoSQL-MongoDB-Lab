"""Tests for the Chapter 7 / Chapter 14 dashboard metrics and the chat's live-context input."""

import os
from datetime import datetime, timedelta, timezone

import mongomock

os.environ["LLM_BACKEND"] = "extractive"

from fastapi.testclient import TestClient  # noqa: E402

from app import chat_api, dashboard_metrics as dm, llm  # noqa: E402

STATUS = {"version": "7.0.14", "uptime": 3600, "connections": {"current": 900, "available": 100},
          "opcounters": {"insert": 100, "query": 400, "update": 10, "delete": 0, "command": 50}, "mem": {"resident": 300},
          "wiredTiger": {"cache": {"bytes currently in the cache": 90, "maximum bytes configured": 100,
                                   "tracked dirty bytes in the cache": 5, "pages read into cache": 50000,
                                   "pages requested from the cache": 100000, "eviction pages evicted by application threads": 5000}}}


def test_cache_parsing_and_ratios():
    m = dm.parse_metrics(STATUS)
    assert m["cache_used_pct"] == 90.0
    assert m["hit_ratio"] == 0.5          # half of the page requests had to read from disk
    assert m["hit_ratio_lab"] == 0.9      # the lab's eviction-based approximation


def test_alerts_fire_on_chapter14_thresholds():
    m = dm.parse_metrics(STATUS)
    al = dm.alerts(m)
    assert any("Cache usage" in a for a in al)
    assert any("Connections near limit" in a for a in al)
    assert any("hit ratio" in a for a in al)
    now = datetime.now(timezone.utc)
    lag = dm.alerts({}, [{"stateStr": "PRIMARY", "optimeDate": now, "name": "a"},
                         {"stateStr": "SECONDARY", "optimeDate": now - timedelta(seconds=30), "name": "b"}])
    assert lag == ["Replication lag 30s on b"]


def test_rates_between_samples():
    a = dm.parse_metrics(STATUS)
    b = dict(a, timestamp=a["timestamp"] + timedelta(seconds=10), op_query=a["op_query"] + 50)
    assert dm.rates(a, b)["query/s"] == 5.0


def test_document_growth_projection():
    assert dm.project_size(100) < dm.project_size(1000) < dm.project_size(100000)
    assert dm.project_size(dm.comments_to_limit() + 1000) > dm.DOC_LIMIT > dm.project_size(dm.comments_to_limit() - 1000)
    assert dm.embed_verdict(10).startswith("EMBED") and dm.embed_verdict(5000).startswith("PAGINATED")


def test_doc_sizes_on_seeded_posts():
    db = mongomock.MongoClient().nosql_labs
    db.blog_posts.insert_many([dict(p) for p in dm.BLOG_POSTS])
    rows = dm.collect_doc_sizes(db, "blog_posts")
    assert len(rows) == 3 and all(r["bytes"] > 200 for r in rows)


def test_summary_text_contains_live_numbers():
    m = dm.parse_metrics(STATUS)
    s = dm.summarise(m, [{"title": "Post", "comments": 2, "bytes": 348}], None, dm.alerts(m), (1000, dm.project_size(1000)))
    assert "90.0%" in s and "348 B" in s and "Active alerts: Cache usage" in s


def test_chat_accepts_dashboard_context():
    llm.LLM_BACKEND = "extractive"
    chat_api.app.state.client = mongomock.MongoClient()
    with TestClient(chat_api.app) as c:
        c.post("/ingest", json={"documents": [{"title": "Working Set", "content": "The WiredTiger cache holds the working set."}]})
        r = c.post("/chat", json={"session_id": "d1", "message": "explain my cache", "context": "WiredTiger cache: 90% used"}).json()
        assert "90% used" in r["response"]
        assert c.post("/chat", json={"session_id": "d1", "message": "x", "context": "y" * 5000}).status_code == 422
    chat_api.app.state.client = None
