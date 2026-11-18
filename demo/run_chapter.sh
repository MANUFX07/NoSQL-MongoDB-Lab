#!/usr/bin/env bash
# Run every lab of one chapter, pausing between scripts - for demonstrations in VS Code.
#
#   bash demo/run_chapter.sh 5        # run chapter 5
#   bash demo/run_chapter.sh all      # chapters that need only the main MongoDB (1-7, 11, 14-18)
#
# Run from the repository root with the virtual environment active
# (source .venv/Scripts/activate on Windows Git Bash, source .venv/bin/activate elsewhere).
set -u
export MSYS_NO_PATHCONV=1          # stop Git Bash rewriting "/CN=..." and container paths
cd "$(dirname "$0")/.."
PY=python
command -v python >/dev/null 2>&1 || PY=python3

pause() { read -r -p $'\n>>> Press Enter to continue (Ctrl+C to stop) ' _; }
title() { printf '\n\033[1;36m%s\n%s\033[0m\n' "==================== $1 ====================" "$2"; }
run_py() { echo -e "\n\033[1;33m\$ python $1\033[0m"; $PY "$@"; pause; }
run_sh() { echo -e "\n\033[1;33m\$ bash $1\033[0m"; bash "$@"; pause; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "[MISSING] '$1' is not installed or not on PATH - $2"; return 1; }; }
port_owner() { docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E "(0\.0\.0\.0|\[::\]):$1->" | awk '{print $1}' | head -1; }

needs_main_mongo() {
  $PY - <<'PYEOF' || { echo "[MISSING] No MongoDB on localhost:27017. Start it: (cd mini-project && docker compose up -d)"; exit 1; }
from pymongo import MongoClient
MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000).admin.command("ping")
PYEOF
}

needs_replica_set() {
  local owner; owner=$(port_owner 27017)
  if [ -n "$owner" ] && [ "$owner" != "mongo-rs0-1" ]; then
    echo "[STOP] Port 27017 is used by '$owner'. Stop it first:"
    echo "       (cd mini-project && docker compose down)   # or: docker stop $owner"
    exit 1
  fi
  if [ "$owner" != "mongo-rs0-1" ]; then
    need mongosh "install MongoDB Shell: https://www.mongodb.com/try/download/shell" || exit 1
    echo "Replica set not running - deploying it (Lab 8.1)..."
    bash chapter-08/lab_01_deploy_replicaset.sh
  fi
}

chapter() {
  case "$1" in
    1) title "Chapter 1" "Why NoSQL? - classify databases, map an application to NoSQL families"
       run_py chapter-01/lab_01_classify_databases.py; run_py chapter-01/lab_02_map_application.py ;;
    2) title "Chapter 2" "Environment setup and first CRUD"; needs_main_mongo
       run_py chapter-02/lab_01_setup_environment.py; run_py chapter-02/first_connection.py; run_py chapter-02/lab_02_bookstore_crud.py ;;
    3) title "Chapter 3" "Data model: BSON, embedding vs referencing, schema validation"; needs_main_mongo
       run_py chapter-03/bson_exploration.py; run_py chapter-03/lab_01_embedded_schema.py
       run_py chapter-03/lab_02_embed_vs_reference.py; run_py chapter-03/schema_validation.py ;;
    4) title "Chapter 4" "Queries, upserts, bulk writes, idempotency"; needs_main_mongo
       run_py chapter-04/lab_01_product_query_api.py; run_py chapter-04/lab_02_upsert_bulk.py ;;
    5) title "Chapter 5" "Aggregation framework and \$lookup joins"; needs_main_mongo
       run_py chapter-05/lab_01_sales_analytics.py; run_py chapter-05/lab_02_lookup_joins.py ;;
    6) title "Chapter 6" "Indexing and explain() plans"; needs_main_mongo
       run_py chapter-06/lab_01_index_design.py; run_py chapter-06/lab_02_index_strategies.py ;;
    7) title "Chapter 7" "Architecture: \$bsonSize and the working set  (then show the dashboard: http://localhost:8502)"; needs_main_mongo
       run_py chapter-07/lab_01_production_schema.py; run_py chapter-07/lab_02_working_set_analysis.py ;;
    8) title "Chapter 8" "Replication: 3-member replica set + automatic failover"; needs_replica_set
       echo "In a SECOND terminal (+ in the terminal panel) run:  bash demo/stepdown.sh   while the observer is running."
       run_py chapter-08/lab_02_failover_observer.py ;;
    9) title "Chapter 9" "CAP theorem: write-concern latency + simulated partition"; needs_replica_set
       run_py chapter-09/lab_01_write_concern_latency.py; run_sh chapter-09/lab_02_simulate_partition.sh ;;
    10) title "Chapter 10" "Multi-document ACID transactions"; needs_replica_set
       MONGO_URI="mongodb://localhost:27017/?directConnection=true" run_py chapter-10/lab_01_bank_transfer.py
       MONGO_URI="mongodb://localhost:27017/?directConnection=true" run_py chapter-10/lab_02_inventory_reservation.py ;;
    11) title "Chapter 11" "Sharding: shard-key evaluation and hotspot simulation"
       run_py chapter-11/lab_01_shard_key_eval.py; run_py chapter-11/lab_02_shard_key_hotspot.py ;;
    12) title "Chapter 12" "Security: RBAC (own container with --auth), TLS, field redaction"
       run_sh demo/ch12_rbac_docker.sh
       run_sh demo/ch12_tls_docker.sh
       needs_main_mongo && run_py chapter-12/rbac_field_redaction.py ;;
    13) title "Chapter 13" "Deployment: production replica set with keyFile auth, Kubernetes StatefulSet"
       run_sh demo/ch13_deploy_prod_docker.sh
       run_py chapter-13/lab_02_k8s_statefulset.py ;;
    14) title "Chapter 14" "Production operations: monitoring dashboard (30 s) and verified backup/restore"; needs_main_mongo
       run_py chapter-14/lab_01_monitoring_dashboard.py
       if need mongodump "install MongoDB Database Tools: https://www.mongodb.com/try/download/database-tools"; then
         run_py chapter-14/lab_02_backup_restore.py
       else echo "Skipping Lab 14.2 until the tools are installed."; pause; fi ;;
    15) title "Chapter 15" "Multi-tenant SaaS data layer and tenant migration"; needs_main_mongo
       run_py chapter-15/lab_01_multitenant_api.py; run_py chapter-15/lab_02_tenant_migration.py ;;
    16) title "Chapter 16" "Polyglot persistence: MongoDB vs Cassandra vs Neo4j"; needs_main_mongo
       run_py chapter-16/lab_01_polyglot_modeling.py; run_py chapter-16/lab_02_hybrid_query_service.py ;;
    17) title "Chapter 17" "Vector search and RAG; HNSW vs IVF"; needs_main_mongo
       run_py chapter-17/lab_01_rag_pipeline.py; run_py chapter-17/lab_02_hnsw_vs_ivf.py ;;
    18) title "Chapter 18" "Comparative capstone benchmark and report"; needs_main_mongo
       run_py chapter-18/lab_01_comparative_capstone.py; run_py chapter-18/lab_02_comparative_report.py ;;
    *) echo "Unknown chapter '$1'. Use 1-18 or 'all'."; exit 1 ;;
  esac
}

if [ "${1:-}" = "all" ]; then
  for c in 1 2 3 4 5 6 7 11 14 15 16 17 18; do chapter "$c"; done
  echo -e "\nDone. Chapters 8, 9, 10, 12 and 13 need their own MongoDB setups - run them one by one (see demo/DEMO_GUIDE.md)."
else
  chapter "${1:?usage: bash demo/run_chapter.sh <1-18|all>}"
fi
