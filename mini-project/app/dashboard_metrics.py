"""Metrics behind the MongoDB Operations Dashboard (Chapter 7 + Chapter 14).

Chapter 7.1  document size analysis with $bsonSize and the 16 MB limit
Chapter 7.2  working set vs WiredTiger cache (serverStatus.wiredTiger.cache)
Chapter 14.1 monitoring: connections, opcounters, cache usage, threshold alerts

Pure functions (parse_*, project_*, alerts, summarise) take plain dicts so they
can be unit-tested without a server; the collect_* functions talk to MongoDB.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import bson

DOC_LIMIT = 16 * 1024 * 1024
CACHE_ALERT_PCT = 80      # same thresholds as chapter-14/lab_01_monitoring_dashboard.py
CONN_ALERT_RATIO = 0.8

# Lab 7.1 seed data (chapter-07/lab_01_production_schema.py)
BLOG_POSTS = [
    {"title": "Getting Started with MongoDB", "author": "arjun", "slug": "getting-started-mongodb",
     "tags": ["mongodb", "nosql", "beginner"],
     "comments": [{"author": "reader1", "text": "Great intro!", "created": "2024-01-16"},
                  {"author": "reader2", "text": "More on aggregation please", "created": "2024-01-17"}]},
    {"title": "Advanced Aggregation Pipelines", "author": "sneha", "slug": "advanced-aggregation",
     "tags": ["mongodb", "aggregation", "intermediate"],
     "comments": [{"author": "reader1", "text": "$facet is amazing", "created": "2024-02-01"},
                  {"author": "reader3", "text": "Very well explained", "created": "2024-02-02"},
                  {"author": "reader4", "text": "Bookmarking this", "created": "2024-02-03"}]},
    {"title": "Vector Search with MongoDB Atlas", "author": "kavya", "slug": "vector-search-atlas",
     "tags": ["mongodb", "ai", "vector-search", "advanced"],
     "comments": [{"author": "reader5", "text": "When is IVF better than HNSW?", "created": "2024-03-01"}]},
]


# ----------------------------------------------------------- Chapter 7.1
def embed_verdict(comments: int) -> str:
    """Rules printed by Lab 7.1."""
    if comments < 100:
        return "EMBED - fewer queries, faster reads"
    if comments <= 1000:
        return "REFERENCE - avoid the 16 MB document limit"
    return "PAGINATED REFERENCE - bucket pattern"


def sample_post(n_comments: int) -> dict:
    return {"title": "Popular Post", "author": "celebrity",
            "comments": [{"author": f"user{i}", "text": f"Comment number {i}"} for i in range(n_comments)]}


def project_size(n_comments: int) -> int:
    """Exact BSON size of a post with n comments (exact encode up to 20k, then linear extrapolation)."""
    if n_comments <= 20000:
        return len(bson.encode(sample_post(n_comments)))
    base, s20k = len(bson.encode(sample_post(0))), len(bson.encode(sample_post(20000)))
    return int(base + (s20k - base) / 20000 * n_comments)


def comments_to_limit() -> int:
    base, s = len(bson.encode(sample_post(0))), len(bson.encode(sample_post(20000)))
    return int((DOC_LIMIT - base) / ((s - base) / 20000))


def collect_doc_sizes(db, collection: str) -> list[dict]:
    pipeline = [{"$project": {"_id": 0, "title": 1, "comments": {"$size": {"$ifNull": ["$comments", []]}},
                              "bytes": {"$bsonSize": "$$ROOT"}}}, {"$sort": {"bytes": -1}}]
    try:
        return list(db[collection].aggregate(pipeline))
    except Exception:  # servers/mocks without $bsonSize
        return [{"title": d.get("title"), "comments": len(d.get("comments", [])), "bytes": len(bson.encode(d))}
                for d in db[collection].find()]


def collection_size_stats(db, collection: str) -> dict | None:
    try:
        r = list(db[collection].aggregate([{"$group": {"_id": None, "docs": {"$sum": 1},
                                                       "avg": {"$avg": {"$bsonSize": "$$ROOT"}},
                                                       "max": {"$max": {"$bsonSize": "$$ROOT"}}}}]))
    except Exception:
        sizes = [len(bson.encode(d)) for d in db[collection].find()]
        r = [{"docs": len(sizes), "avg": sum(sizes) / len(sizes), "max": max(sizes)}] if sizes else []
    if not r:
        return None
    return {"collection": f"{db.name}.{collection}", "documents": r[0]["docs"], "avg_bytes": round(r[0]["avg"] or 0),
            "max_bytes": r[0]["max"], "pct_of_16mb": round(100 * (r[0]["max"] or 0) / DOC_LIMIT, 4)}


# ----------------------------------------------------------- Chapter 7.2
def parse_cache(status: dict) -> dict:
    c = status.get("wiredTiger", {}).get("cache", {})
    used, cap = c.get("bytes currently in the cache", 0), c.get("maximum bytes configured", 0)
    read_in, requested = c.get("pages read into cache", 0), c.get("pages requested from the cache", 0)
    evicted = c.get("eviction pages evicted by application threads", 0)
    return {
        "cache_max_bytes": cap, "cache_used_bytes": used, "cache_used_pct": round(100 * used / cap, 1) if cap else 0.0,
        "cache_dirty_bytes": c.get("tracked dirty bytes in the cache", 0),
        "pages_read_into_cache": read_in, "pages_requested": requested, "pages_evicted_by_app": evicted,
        # Lab 7.2's approximation, kept for comparison with the lab output
        "hit_ratio_lab": round(max(0.0, 1 - evicted / read_in), 4) if read_in else None,
        # share of page requests served from memory without reading from disk
        "hit_ratio": round(max(0.0, 1 - read_in / requested), 4) if requested else None,
    }


def collect_storage(client, db_names: list[str]) -> list[dict]:
    rows = []
    for name in db_names:
        db = client[name]
        try:
            cols = db.list_collection_names()
        except Exception:
            continue
        for col in cols:
            try:
                st = db.command("collStats", col)
            except Exception:
                continue
            if st.get("type") == "view" or "size" not in st:
                continue
            rows.append({"collection": f"{name}.{col}", "documents": st.get("count", 0), "data_bytes": st.get("size", 0),
                         "index_bytes": st.get("totalIndexSize", 0)})
    return sorted(rows, key=lambda r: r["data_bytes"] + r["index_bytes"], reverse=True)


def seed_working_set(db, count: int, batch: int = 5000, progress=None) -> float:
    """Lab 7.2 data: ~2 KB sensor documents."""
    db.working_set_docs.drop()
    t0 = time.perf_counter()
    for start in range(0, count, batch):
        db.working_set_docs.insert_many([{"sensor": f"S-{i:06d}", "reading": i * 0.01, "metadata": "x" * 1800}
                                         for i in range(start, min(count, start + batch))])
        if progress:
            progress(min(count, start + batch) / count)
    return time.perf_counter() - t0


def range_query_test(db) -> list[dict]:
    n = db.working_set_docs.estimated_document_count()
    if not n:
        return []
    out = []
    for label, lo in (("start", 0), ("middle", n // 2 - 500), ("end", n - 1000)):
        lo = max(0, lo)
        t0 = time.perf_counter()
        got = len(list(db.working_set_docs.find({"sensor": {"$gte": f"S-{lo:06d}", "$lte": f"S-{lo + 1000:06d}"}})))
        out.append({"range": f"{label} ({lo:,}-{lo + 1000:,})", "documents": got, "ms": round((time.perf_counter() - t0) * 1000, 1)})
    return out


# ---------------------------------------------------------- Chapter 14.1
def parse_metrics(status: dict) -> dict:
    conn, ops = status.get("connections", {}), status.get("opcounters", {})
    m = {"timestamp": datetime.now(timezone.utc), "uptime_s": status.get("uptime", 0), "version": status.get("version"),
         "connections_current": conn.get("current", 0), "connections_available": conn.get("available", 0),
         "op_insert": ops.get("insert", 0), "op_query": ops.get("query", 0), "op_update": ops.get("update", 0),
         "op_delete": ops.get("delete", 0), "op_command": ops.get("command", 0),
         "mem_resident_mb": status.get("mem", {}).get("resident", 0),
         "net_in_bytes": status.get("network", {}).get("bytesIn", 0), "net_out_bytes": status.get("network", {}).get("bytesOut", 0)}
    m.update(parse_cache(status))
    return m


def alerts(m: dict, repl_members: list[dict] | None = None) -> list[str]:
    out = []
    if m.get("cache_used_pct", 0) > CACHE_ALERT_PCT:
        out.append(f"Cache usage {m['cache_used_pct']:.1f}% exceeds {CACHE_ALERT_PCT}%")
    total = m.get("connections_current", 0) + m.get("connections_available", 0)
    if total and m.get("connections_current", 0) > CONN_ALERT_RATIO * total:
        out.append(f"Connections near limit: {m['connections_current']}/{total}")
    if m.get("hit_ratio") is not None and m["hit_ratio"] < 0.95 and m.get("pages_requested", 0) > 10000:
        out.append(f"Cache hit ratio {m['hit_ratio']:.1%} - working set may not fit in the cache")
    primary = next((x for x in repl_members or [] if x.get("stateStr") == "PRIMARY"), None)
    for x in repl_members or []:
        if primary and x.get("stateStr") == "SECONDARY":
            lag = (primary["optimeDate"] - x["optimeDate"]).total_seconds()
            if lag > 10:
                out.append(f"Replication lag {lag:.0f}s on {x['name']}")
    return out


def rates(prev: dict | None, cur: dict) -> dict:
    """Operations per second between two samples."""
    if not prev:
        return {}
    dt = (cur["timestamp"] - prev["timestamp"]).total_seconds() or 1
    return {k.replace("op_", "") + "/s": round(max(0, cur[k] - prev[k]) / dt, 2)
            for k in ("op_insert", "op_query", "op_update", "op_delete", "op_command")}


def collect_status(client) -> dict:
    return client.admin.command("serverStatus")


def replica_members(client) -> list[dict]:
    try:
        return client.admin.command("replSetGetStatus").get("members", [])
    except Exception:
        return []


# ------------------------------------------------------ context for chat
def summarise(m: dict | None = None, sizes: list[dict] | None = None, storage: list[dict] | None = None,
              alert_list: list[str] | None = None, projection: tuple[int, int] | None = None) -> str:
    """Compact text of the current readings, sent to the chat backend as live context."""
    mb = lambda b: f"{(b or 0) / 1048576:.1f} MB"  # noqa: E731
    lines = []
    if m:
        hr = f"{m['hit_ratio']:.1%}" if m.get("hit_ratio") is not None else "n/a"
        lines += [f"WiredTiger cache: {mb(m['cache_used_bytes'])} used of {mb(m['cache_max_bytes'])} ({m['cache_used_pct']}%), "
                  f"dirty {mb(m['cache_dirty_bytes'])}; pages read into cache {m['pages_read_into_cache']:,}, "
                  f"requested {m['pages_requested']:,}, evicted by app threads {m['pages_evicted_by_app']:,}; hit ratio {hr}.",
                  f"Connections {m['connections_current']} current / {m['connections_available']} available; "
                  f"opcounters insert {m['op_insert']:,}, query {m['op_query']:,}, update {m['op_update']:,}, delete {m['op_delete']:,}; "
                  f"resident memory {m['mem_resident_mb']} MB; uptime {m['uptime_s'] // 3600} h; MongoDB {m.get('version')}."]
    if storage:
        total = sum(r["data_bytes"] + r["index_bytes"] for r in storage)
        top = ", ".join(f"{r['collection']} {mb(r['data_bytes'] + r['index_bytes'])}" for r in storage[:4])
        lines.append(f"Data + indexes total {mb(total)} (largest: {top}).")
    if sizes:
        lines.append("Blog post sizes ($bsonSize): " + ", ".join(f"'{s['title']}' {s['comments']} comments = {s['bytes']} B" for s in sizes[:5]) + ".")
    if projection:
        n, size = projection
        lines.append(f"Projected post with {n:,} comments = {mb(size)} ({100 * size / DOC_LIMIT:.1f}% of the 16 MB limit); verdict: {embed_verdict(n)}.")
    lines.append("Active alerts: " + ("; ".join(alert_list) if alert_list else "none") + ".")
    return "\n".join(lines)
