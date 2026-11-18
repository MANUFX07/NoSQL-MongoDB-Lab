#!/usr/bin/env bash
# Lab 12.2 with mongod running in Docker (no local mongod needed): generate a CA + server
# certificate, require TLS on port 27100, prove plain connections fail and TLS ones succeed.
set -e
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../chapter-12"
PY=python; command -v python >/dev/null 2>&1 || PY=python3
D=tls; mkdir -p "$D"
if [ ! -f "$D/mongodb.pem" ]; then
  echo "=== Step 1: Generating CA and server certificate ==="
  openssl req -newkey rsa:2048 -new -x509 -days 365 -nodes -out "$D/ca.crt" -keyout "$D/ca.key" -subj "/CN=NoSQL-Labs-CA" 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -keyout "$D/server.key" -out "$D/server.csr" -subj "/CN=localhost" 2>/dev/null
  openssl x509 -req -in "$D/server.csr" -CA "$D/ca.crt" -CAkey "$D/ca.key" -CAcreateserial -out "$D/server.crt" -days 365 2>/dev/null
  cat "$D/server.key" "$D/server.crt" > "$D/mongodb.pem"
  echo "[OK] certificates in chapter-12/tls/"
fi
HOSTDIR=$(pwd -W 2>/dev/null || pwd)/$D
echo -e "\n=== Step 2: Starting mongod with --tlsMode requireTLS on port 27100 ==="
docker rm -f mongo-tls-lab >/dev/null 2>&1 || true
docker run -d --name mongo-tls-lab -p 27100:27100 -v "$HOSTDIR:/tls:ro" mongo:7 \
  mongod --port 27100 --bind_ip_all --tlsMode requireTLS --tlsCertificateKeyFile /tls/mongodb.pem >/dev/null
sleep 6
echo -e "\n=== Step 3: Plain (non-TLS) connection must be rejected ==="
$PY - <<'PYEOF'
from pymongo import MongoClient
try:
    MongoClient("mongodb://localhost:27100", serverSelectionTimeoutMS=3000).admin.command("ping")
    print("[ERROR] non-TLS connection was accepted")
except Exception as e:
    print("[OK] non-TLS connection rejected:", type(e).__name__)
PYEOF
echo -e "\n=== Step 4: TLS connection with the CA certificate must succeed ==="
$PY - "$D/ca.crt" <<'PYEOF'
import sys
from pymongo import MongoClient
c = MongoClient(f"mongodb://localhost:27100/?tls=true&tlsCAFile={sys.argv[1]}&tlsAllowInvalidHostnames=true", serverSelectionTimeoutMS=5000)
c.admin.command("ping")
print("[OK] PyMongo connected over TLS; server version", c.server_info()["version"])
PYEOF
echo -e "\n[OK] TLS lab complete. Remove the container with: docker rm -f mongo-tls-lab"
