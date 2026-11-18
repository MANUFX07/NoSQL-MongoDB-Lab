# Mini Project — LLM/SLM-Backed RAG Chat Application on MongoDB

See the main [README](../README.md#mini-project--llmslm-backed-chat-application-on-mongodb) and the full [Mini Project Report](../reports/Mini_Project_Report.pdf).

| Path | Purpose |
|---|---|
| `app/chat_api.py` | FastAPI service: `/health`, `/ingest`, `/chat`, `/sessions/{id}`, `/stats` |
| `app/embeddings.py` | Embedding backends: `hash` (default, offline), `ollama`, `mock` |
| `app/llm.py` | Generator backends: `ollama` (SLM default `llama3.2:1b`), `openai`, `extractive` |
| `frontend/streamlit_app.py` | Chat UI with source citations (port 8501) |
| `frontend/dashboard_app.py` | **MongoDB Operations Dashboard** - Chapter 7 (document size, working set) + Chapter 14 (monitoring) with the AI chat box built in (port 8502) |
| `app/dashboard_metrics.py` | Metrics behind the dashboard: `$bsonSize`, WiredTiger cache, `serverStatus`, alerts, live-context summary |
| `data/dashboard_kb.json` | Extra knowledge for the assistant (working set, 16 MB limit, monitoring) |
| `scripts/ingest.py` | Loads `data/knowledge_base.json` into the running backend |
| `eval/retrieval_eval.py`, `eval/scaling_eval.py` | Retrieval quality and latency evaluations |
| `tests/test_api.py` | End-to-end tests on mongomock |
| `deploy/atlas_vector_index.json` | Atlas Vector Search index definition (384-d cosine) |
| `docker-compose.yml` | mongo + ollama + backend + frontend |

Configuration goes through environment variables — see `.env.example`.

## Operations dashboard with the AI chat box (Chapters 7 + 14)

```bash
docker compose up -d --build          # now also starts the dashboard service
# open http://localhost:8502
```

| Tab | What it shows |
|---|---|
| Ch 7 - Document size | `$bsonSize` of the Lab 7.1 blog posts, a growth simulator against the 16 MB limit with the lab's embed/reference verdict, and the chat app's own document sizes |
| Ch 7 - Working set | WiredTiger cache usage, dirty bytes, pages read/requested/evicted, hit ratio (and the lab's version), data + indexes vs cache, and the Lab 7.2 insert + range-query experiment |
| Ch 14 - Monitoring | Live `serverStatus` every 5 s: connections, operations/s, memory, uptime, the lab's threshold alerts, replication lag, samples logged to `nosql_labs.monitoring_log` |
| AI assistant (right panel) | The RAG chat. With *Include my live dashboard readings* ticked, the current numbers are sent to `/chat` as `context`, so the SLM explains **your** server, not just the theory |

Click **Teach the assistant Chapter 7 & 14 topics** once to ingest `data/dashboard_kb.json`.
Without Docker: `streamlit run frontend/dashboard_app.py --server.port 8502` (with the backend running).
