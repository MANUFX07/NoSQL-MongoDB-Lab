# Mini Project — LLM/SLM-Backed RAG Chat Application on MongoDB

See the main [README](../README.md#mini-project--llmslm-backed-chat-application-on-mongodb) and the full [Mini Project Report](../reports/Mini_Project_Report.pdf).

| Path | Purpose |
|---|---|
| `app/chat_api.py` | FastAPI service: `/health`, `/ingest`, `/chat`, `/sessions/{id}`, `/stats` |
| `app/embeddings.py` | Embedding backends: `hash` (default, offline), `ollama`, `mock` |
| `app/llm.py` | Generator backends: `ollama` (SLM default `llama3.2:1b`), `openai`, `extractive` |
| `frontend/streamlit_app.py` | Chat UI with source citations |
| `scripts/ingest.py` | Loads `data/knowledge_base.json` into the running backend |
| `eval/retrieval_eval.py`, `eval/scaling_eval.py` | Retrieval quality and latency evaluations |
| `tests/test_api.py` | End-to-end tests on mongomock |
| `deploy/atlas_vector_index.json` | Atlas Vector Search index definition (384-d cosine) |
| `docker-compose.yml` | mongo + ollama + backend + frontend |

Configuration goes through environment variables — see `.env.example`.
