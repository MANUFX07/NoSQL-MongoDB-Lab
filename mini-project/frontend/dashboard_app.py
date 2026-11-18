"""MongoDB Operations Dashboard with the AI chat assistant built in.

    Chapter 7.1   Document size analysis ($bsonSize, 16 MB limit, embed vs reference)
    Chapter 7.2   Working set vs WiredTiger cache, range-query test
    Chapter 14.1  Live monitoring: connections, opcounters, cache, alerts, metric log
    AI assistant  The mini-project RAG chat (FastAPI + MongoDB + Ollama SLM), which
                  can include the dashboard's live readings in its answer

    streamlit run frontend/dashboard_app.py --server.port 8502
"""

import json
import os
import sys
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import dashboard_metrics as dm  # noqa: E402

MONGO_URI = os.getenv("DASHBOARD_MONGO_URI") or os.getenv("MONGO_URI", "mongodb://localhost:27017")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
LAB_DB = os.getenv("LAB_DB", "nosql_labs")
APP_DB = os.getenv("MONGO_DB", "llm_chat_app")
KB_FILE = Path(__file__).resolve().parents[1] / "data" / "dashboard_kb.json"

st.set_page_config(page_title="MongoDB Ops Dashboard + AI", page_icon="📊", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 1.2rem;}
div[data-testid="stMetricValue"] {font-size: 1.5rem;}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def mongo():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000, appname="ops-dashboard")


client = mongo()
lab = client[LAB_DB]
for key, default in (("session_id", f"dash-{uuid.uuid4().hex[:10]}"), ("chat", []), ("prev_sample", None),
                     ("history", []), ("projection", (1000, dm.project_size(1000))), ("sizes", []), ("storage", []),
                     ("range_results", [])):
    st.session_state.setdefault(key, default)

try:
    client.admin.command("ping")
    connected = True
except Exception as exc:
    connected = False
    st.error(f"Cannot reach MongoDB at {MONGO_URI}: {exc}")

st.title("📊 MongoDB Operations Dashboard")
st.caption("Chapter 7 (architecture: document size, working set) + Chapter 14 (monitoring) — with the RAG AI assistant from the mini project")

main, side = st.columns([2.3, 1], gap="large")


def current_metrics():
    if not connected:
        return None, []
    try:
        m = dm.parse_metrics(dm.collect_status(client))
    except Exception as exc:
        st.warning(f"serverStatus unavailable: {exc}")
        return None, []
    return m, dm.alerts(m, dm.replica_members(client))


# =================================================================== tabs
with main:
    t71, t72, t14 = st.tabs(["🧱 Ch 7 · Document size", "🧠 Ch 7 · Working set", "📈 Ch 14 · Monitoring"])

    # ------------------------------------------------------ Chapter 7.1
    with t71:
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Seed Lab 7.1 blog posts", help="Resets nosql_labs.blog_posts with the lab's three posts"):
                lab.blog_posts.drop()
                lab.blog_posts.insert_many([json.loads(json.dumps(p)) for p in dm.BLOG_POSTS])
                st.success("Inserted 3 blog posts")
        st.session_state.sizes = dm.collect_doc_sizes(lab, "blog_posts") if connected else []
        if st.session_state.sizes:
            df = pd.DataFrame(st.session_state.sizes)
            df["pattern"] = df["comments"].map(lambda n: "Embedded comments" if n <= 5 else "Consider referencing")
            st.subheader("Document sizes measured with $bsonSize")
            st.dataframe(df.rename(columns={"bytes": "BSON bytes"}), hide_index=True, width="stretch")
        else:
            st.info("No blog posts yet - click **Seed Lab 7.1 blog posts**.")

        st.subheader("What if a post keeps collecting comments?")
        n = st.select_slider("Comments on one post", options=[10, 100, 500, 1000, 5000, 10000, 50000, 100000, 200000, 400000], value=1000)
        size = dm.project_size(n)
        st.session_state.projection = (n, size)
        pct = size / dm.DOC_LIMIT
        k1, k2, k3 = st.columns(3)
        k1.metric("Projected document size", f"{size / 1048576:.2f} MB" if size > 1048576 else f"{size / 1024:.1f} KB")
        k2.metric("Share of 16 MB limit", f"{pct:.1%}")
        k3.metric("Comments until the limit", f"{dm.comments_to_limit():,}")
        st.progress(min(1.0, pct), text=dm.embed_verdict(n))
        curve = pd.DataFrame({"comments": [100, 1000, 10000, 50000, 100000, 200000, 400000]})
        curve["size_MB"] = curve["comments"].map(lambda c: round(dm.project_size(c) / 1048576, 3))
        curve["limit_MB"] = 16.0
        st.line_chart(curve.set_index("comments"), height=220)
        if pct >= 1:
            st.error("This document would be rejected by MongoDB - comments must live in their own collection (or buckets).")

        st.subheader("The chat app's own documents")
        rows = [r for r in (dm.collection_size_stats(client[APP_DB], c) for c in ("document_chunks", "sessions")) if r] if connected else []
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Chunks are stored one per document and chat history is capped at 40 messages with $push + $slice, "
                       "so neither collection can grow a document towards the 16 MB limit.")
        else:
            st.caption("Start the chat backend and ingest documents to see its collections here.")

    # ------------------------------------------------------ Chapter 7.2
    with t72:
        m, _ = current_metrics()
        if m:
            a, b, c, d = st.columns(4)
            a.metric("Cache in use", f"{m['cache_used_bytes'] / 1048576:.1f} MB", f"{m['cache_used_pct']}% of {m['cache_max_bytes'] / 1048576:.0f} MB", delta_color="off")
            b.metric("Dirty bytes", f"{m['cache_dirty_bytes'] / 1048576:.1f} MB")
            c.metric("Cache hit ratio", f"{m['hit_ratio']:.2%}" if m["hit_ratio"] is not None else "n/a",
                     help="1 - pages read into cache / pages requested from the cache")
            d.metric("Lab 7.2 ratio", f"{m['hit_ratio_lab']:.2%}" if m["hit_ratio_lab"] is not None else "n/a",
                     help="The lab's approximation: 1 - pages evicted by application threads / pages read into cache")
            st.progress(min(1.0, m["cache_used_pct"] / 100), text=f"WiredTiger cache {m['cache_used_pct']}% full")
            e1, e2, e3 = st.columns(3)
            e1.metric("Pages read into cache", f"{m['pages_read_into_cache']:,}")
            e2.metric("Pages requested", f"{m['pages_requested']:,}")
            e3.metric("Evicted by app threads", f"{m['pages_evicted_by_app']:,}")

        st.subheader("Does the data fit in the cache?")
        st.session_state.storage = dm.collect_storage(client, [LAB_DB, APP_DB]) if connected else []
        if st.session_state.storage and m:
            sdf = pd.DataFrame(st.session_state.storage)
            sdf["total_MB"] = ((sdf["data_bytes"] + sdf["index_bytes"]) / 1048576).round(2)
            total = sdf["total_MB"].sum()
            cap = m["cache_max_bytes"] / 1048576
            st.bar_chart(sdf.set_index("collection")["total_MB"].head(10), height=240, horizontal=True)
            (st.success if total < cap else st.error)(
                f"Data + indexes: {total:.1f} MB vs cache {cap:.0f} MB -> working set {'fits' if total < cap else 'does NOT fit'} in memory")

        st.subheader("Lab 7.2 experiment")
        cnt = st.number_input("Documents (~2 KB each)", 1000, 100000, 20000, step=5000)
        x1, x2 = st.columns(2)
        if x1.button("Insert working-set documents"):
            bar = st.progress(0.0, text="inserting...")
            secs = dm.seed_working_set(lab, int(cnt), progress=lambda f: bar.progress(f, text=f"inserting... {f:.0%}"))
            st.success(f"Inserted {int(cnt):,} documents in {secs:.1f}s ({cnt / secs:,.0f} docs/s)")
        if x2.button("Run range-query test"):
            st.session_state.range_results = dm.range_query_test(lab)
        if st.session_state.range_results:
            st.dataframe(pd.DataFrame(st.session_state.range_results), hide_index=True, width="stretch")
            st.caption("Ranges written most recently are most likely still in cache; with no index on 'sensor' every range is a full collection scan.")

    # ----------------------------------------------------- Chapter 14.1
    with t14:
        auto = st.toggle("Auto-refresh every 5 s", value=True)

        @st.fragment(run_every=5 if auto else None)
        def monitor():
            m, al = current_metrics()
            if not m:
                return
            r = dm.rates(st.session_state.prev_sample, m)
            st.session_state.prev_sample = m
            if r:
                st.session_state.history = (st.session_state.history + [{"time": m["timestamp"], **r}])[-120:]
            try:  # metric log, as in the lab's metrics.log, but stored in MongoDB
                lab.monitoring_log.insert_one({k: v for k, v in m.items()} | {"alerts": al})
            except Exception:
                pass
            k = st.columns(5)
            k[0].metric("Connections", m["connections_current"], f"{m['connections_available']:,} available", delta_color="off")
            k[1].metric("Cache usage", f"{m['cache_used_pct']}%")
            k[2].metric("Resident memory", f"{m['mem_resident_mb']} MB")
            k[3].metric("Uptime", f"{m['uptime_s'] // 3600} h {(m['uptime_s'] % 3600) // 60} m")
            k[4].metric("MongoDB", m.get("version") or "-")
            if al:
                for x in al:
                    st.error(f"ALERT: {x}")
            else:
                st.success(f"No alerts (thresholds: cache > {dm.CACHE_ALERT_PCT}%, connections > {int(dm.CONN_ALERT_RATIO * 100)}%, replication lag > 10 s)")
            o = st.columns(4)
            for col, key in zip(o, ("op_insert", "op_query", "op_update", "op_delete")):
                col.metric(key.replace("op_", "").title() + " ops", f"{m[key]:,}", f"{r.get(key.replace('op_', '') + '/s', 0)}/s" if r else None)
            if len(st.session_state.history) > 1:
                st.caption("Operations per second")
                st.line_chart(pd.DataFrame(st.session_state.history).set_index("time"), height=220)
            st.caption(f"Samples logged to {LAB_DB}.monitoring_log: {lab.monitoring_log.estimated_document_count():,}")

        monitor()

# ============================================================ AI assistant
with side:
    st.subheader("💬 AI assistant")
    try:
        h = requests.get(f"{BACKEND_URL}/health", timeout=3).json()
        stats = requests.get(f"{BACKEND_URL}/stats", timeout=3).json()
        st.caption(f"{h['llm_backend']} · {h['model']} · {stats['chunks']} chunks from {stats['sources']} sources")
        if not any(True for _ in client[APP_DB].document_chunks.find({"source_title": "Working Set and WiredTiger Cache"}).limit(1)):
            if st.button("Teach the assistant Chapter 7 & 14 topics", help="Ingests data/dashboard_kb.json through /ingest"):
                r = requests.post(f"{BACKEND_URL}/ingest", json={"documents": json.loads(KB_FILE.read_text()), "chunk_size": 80}, timeout=120)
                st.success(f"Ingested: {r.json()}")
        backend_ok = True
    except Exception:
        backend_ok = False
        st.error(f"Chat backend not reachable at {BACKEND_URL}")

    use_live = st.checkbox("Include my live dashboard readings", value=True,
                           help="Sends the current cache, connection, size and alert numbers with your question")
    box = st.container(height=470, border=True)
    with box:
        if not st.session_state.chat:
            st.caption("Ask about what you see, e.g. *Explain my cache hit ratio*, *Is embedding comments safe here?*, *Any problems on my server?*")
        for msg in st.session_state.chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("meta"):
                    st.caption(msg["meta"])

    quick = st.columns(3)
    preset = None
    for col, (label, q) in zip(quick, (("Cache usage?", "Explain my WiredTiger cache usage and whether my working set fits in memory"),
                                       ("Embed or reference?", "Should blog comments be embedded or referenced, given the document sizes on my dashboard?"),
                                       ("Any alerts?", "Are there any problems or alerts on my MongoDB server right now, and what should I do?"))):
        if col.button(label, width="stretch", help=q):
            preset = q
    with st.form("ask", clear_on_submit=True):
        typed = st.text_input("Your question", placeholder="Ask about MongoDB or this dashboard...", label_visibility="collapsed")
        sent = st.form_submit_button("Send", width="stretch")
    question = preset or (typed if sent and typed.strip() else None)

    if question and backend_ok:
        live = None
        if use_live:
            m, al = current_metrics()
            live = dm.summarise(m, st.session_state.sizes, st.session_state.storage, al, st.session_state.projection)
        st.session_state.chat.append({"role": "user", "content": question})
        try:
            with st.spinner("Retrieving from MongoDB and generating..."):
                d = requests.post(f"{BACKEND_URL}/chat", timeout=240, json={
                    "session_id": st.session_state.session_id, "message": question, "top_k": 3, "context": live}).json()
            srcs = ", ".join(dict.fromkeys(s["source"] for s in d["sources"]))
            st.session_state.chat.append({"role": "assistant", "content": d["response"],
                                          "meta": f"{d['backend']} · {d['latency_ms']} ms · sources: {srcs}" + (" · with live data" if live else "")})
        except Exception as exc:
            st.session_state.chat.append({"role": "assistant", "content": f"Error: {exc}"})
        st.rerun()
    if st.button("Clear chat", width="stretch"):
        st.session_state.chat = []
        st.session_state.session_id = f"dash-{uuid.uuid4().hex[:10]}"
        st.rerun()
