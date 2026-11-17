"""Load data/knowledge_base.json (or any JSON list of {title, content}) into the running backend.

    python scripts/ingest.py                       # default knowledge base
    python scripts/ingest.py my_docs.json --chunk-size 80
"""
import argparse
import json
import os
from pathlib import Path

import requests

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
DEFAULT = Path(__file__).resolve().parents[1] / "data" / "knowledge_base.json"

ap = argparse.ArgumentParser()
ap.add_argument("file", nargs="?", default=str(DEFAULT))
ap.add_argument("--chunk-size", type=int, default=60)
args = ap.parse_args()

docs = json.loads(Path(args.file).read_text())
try:
    r = requests.post(f"{BACKEND}/ingest", json={"documents": docs, "chunk_size": args.chunk_size}, timeout=300)
    r.raise_for_status()
    print("[OK]", r.json())
    print("[OK] stats:", requests.get(f"{BACKEND}/stats", timeout=10).json())
except requests.exceptions.ConnectionError:
    print(f"[ERROR] Backend not reachable at {BACKEND}. Start it with: uvicorn app.chat_api:app --reload")
