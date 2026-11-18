# Demo guide: Chapters 1-18 + the AI dashboard (Windows, VS Code, Git Bash)

## 0. One-time setup (do this the day before)
1. Docker Desktop running, VS Code terminal set to **Git Bash** (terminal dropdown > Select Default Profile > Git Bash).
2. Install **MongoDB Shell (mongosh)** and **MongoDB Database Tools** (MSI installers from mongodb.com/try/download). Reopen VS Code, then check: `mongosh --version` and `mongodump --version`.
3. From the repository folder:
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate
   pip install -r requirements.txt -r mini-project/requirements.txt
   ```
   If `cassandra-driver` fails to install, delete that line from `requirements.txt` and run the install again.
4. Pull the Docker images once so the demo is not waiting on Wi-Fi:
   `docker pull mongo:7 && (cd mini-project && docker compose pull && docker compose build)`

## 1. Phase A - main MongoDB + AI dashboard (most chapters)
```bash
cd mini-project && docker compose up -d && cd ..
docker compose -f mini-project/docker-compose.yml exec ollama ollama pull llama3.2:1b     # once
docker compose -f mini-project/docker-compose.yml exec backend python scripts/ingest.py   # once
bash demo/run_chapter.sh 1      # ... and 2, 3, 4, 5, 6, 7, 11, 14, 15, 16, 17, 18
```
`bash demo/run_chapter.sh all` runs all of those in order, pausing after every script.

**Dashboard demo (after Chapter 7):** open http://localhost:8502
- click *Teach the assistant Chapter 7 & 14 topics* (once), then *Seed Lab 7.1 blog posts*
- Document size tab: drag the slider to 400,000 comments -> document crosses 16 MB; ask the assistant *Embed or reference?*
- Working set tab: insert 20,000 docs, *Run range-query test*, ask *Cache usage?*
- Monitoring tab: live operations/s and alerts; ask *Any alerts?*
- Show the chat-only app as well: http://localhost:8501

## 2. Phase B - replica set (Chapters 8, 9, 10)
```bash
(cd mini-project && docker compose down)      # frees port 27017 (data is kept)
bash demo/run_chapter.sh 8                    # deploys the 3-node replica set, then the failover observer
#   -> in a second terminal while the observer runs:  bash demo/stepdown.sh
bash demo/run_chapter.sh 9
bash demo/run_chapter.sh 10
(cd chapter-08 && docker compose -f docker-compose-replicaset.yml down)
```

## 3. Phase C - security and deployment (Chapters 12, 13)
```bash
bash demo/run_chapter.sh 13       # production replica set with keyFile auth on 27017-27019 + Kubernetes manifests
docker rm -f prod-mongo-1 prod-mongo-2 prod-mongo-3
(cd mini-project && docker compose up -d)    # bring the main MongoDB back
bash demo/run_chapter.sh 12       # RBAC on its own --auth container, TLS on port 27100, field redaction
```

## What to say for each chapter (one line each)
| Ch | Show | Key point |
|---|---|---|
| 1 | product classification, app mapping | one application usually needs more than one NoSQL family |
| 2 | environment check, bookstore CRUD | `insert/find/update/delete` on nested documents |
| 3 | BSON types, embed vs reference, validator rejects bad docs | embed bounded data, reference unbounded data |
| 4 | operators, pagination, bulk upserts run twice | `$set` is idempotent, `$inc` is not |
| 5 | revenue pipeline, `$lookup`, never-ordered products | `$match` early, `$sort` after `$group` |
| 6 | COLLSCAN -> IXSCAN, write overhead, covered query | ESR rule; indexes cost writes |
| 7 | `$bsonSize`, cache metrics + **dashboard** | the 16 MB limit and the working set |
| 8 | PRIMARY/SECONDARY/ARBITER, failover line | automatic election, driver follows the new primary |
| 9 | latency per write concern, partition | stronger durability = more latency; majority side keeps writing |
| 10 | transfer commit/abort, 10 threads reserving 5 units | no partial writes, no overselling |
| 11 | shard-key verdicts, hotspot counts | monotonic keys create hotspots; hashed keys spread writes |
| 12 | rejected writes/reads, TLS refused vs accepted, masked view | least privilege, encryption in transit, redaction |
| 13 | keyFile replica set healthy, unauthenticated refused, K8s YAML | reproducible secure deployment |
| 14 | metrics table + alerts, restore verified by checksum | a backup is only real once restored |
| 15 | wrong-tenant update modifies 0, rate limit, idempotent migration | tenant isolation in every filter |
| 16 | same data in 3 models, routed queries | polyglot persistence |
| 17 | RAG context, recall vs vectors compared | approximate search trades a little recall for speed |
| 18 | benchmark table + generated report | measured vs estimated, final recommendation |

## If something fails
| Message | Fix |
|---|---|
| `No MongoDB on localhost:27017` | `(cd mini-project && docker compose up -d)` |
| `Port 27017 is used by ...` (Ch 8-10, 13) | stop that container as printed |
| `mongosh: command not found` | install MongoDB Shell, reopen VS Code |
| `mongodump not found` (Ch 14.2) | install MongoDB Database Tools, reopen VS Code |
| replica set never becomes PRIMARY | `docker compose -f chapter-08/docker-compose-replicaset.yml down -v`, run Chapter 8 again |
