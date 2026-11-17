"""Streamlit chat UI for the MongoDB RAG chat service.

    streamlit run frontend/streamlit_app.py --server.port 8501
"""
import os
import uuid

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")  # http://backend:8000 inside Compose

st.set_page_config(page_title="MongoDB RAG Chat", page_icon="💬")
st.title("MongoDB RAG Chat")
st.caption("LLM / SLM answers grounded in documents stored in MongoDB")

if "session_id" not in st.session_state:
    st.session_state.session_id = f"session-{uuid.uuid4().hex[:12]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Settings")
    top_k = st.slider("Passages to retrieve (top-k)", 1, 10, 3)
    try:
        h = requests.get(f"{BACKEND_URL}/health", timeout=3).json()
        s = requests.get(f"{BACKEND_URL}/stats", timeout=3).json()
        st.success(f"Backend: {h['llm_backend']} · {h['model']}")
        st.caption(f"Embeddings: {h['embedding_backend']} · Vector search: {h['vector_search']}")
        st.caption(f"{s['chunks']} chunks from {s['sources']} sources · {s['sessions']} sessions")
    except Exception:
        st.error(f"Backend not reachable at {BACKEND_URL}")
    st.text(f"Session: {st.session_state.session_id}")
    if st.button("New conversation"):
        requests.delete(f"{BACKEND_URL}/sessions/{st.session_state.session_id}", timeout=5)
        st.session_state.session_id = f"session-{uuid.uuid4().hex[:12]}"
        st.session_state.messages = []
        st.rerun()


def show_sources(sources):
    with st.expander(f"Sources ({len(sources)})"):
        for i, s in enumerate(sources, 1):
            st.markdown(f"**[{i}] {s['source']}** · chunk {s['chunk']} · score {s['score']:.3f}")
            st.caption(s["text"][:240] + ("…" if len(s["text"]) > 240 else ""))


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("sources"):
            show_sources(m["sources"])

if prompt := st.chat_input("Ask about NoSQL and MongoDB…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Retrieving and generating…"):
            try:
                r = requests.post(f"{BACKEND_URL}/chat", timeout=180, json={
                    "session_id": st.session_state.session_id, "message": prompt, "top_k": top_k})
                r.raise_for_status()
                d = r.json()
                st.markdown(d["response"])
                st.caption(f"{d['backend']} · {d['latency_ms']} ms (retrieval {d['retrieval_ms']} ms)")
                show_sources(d["sources"])
                st.session_state.messages.append({"role": "assistant", "content": d["response"], "sources": d["sources"]})
            except Exception as e:
                st.error(f"Error: {e}")
