#!/usr/bin/env bash
# Lab 13.1, Windows/macOS-friendly: production replica set with keyFile auth.
# Fixes two problems of running the original script on Docker Desktop:
#   * bind-mounted keyfiles get 0777 permissions and mongod refuses them  -> each container copies
#     the keyfile, chmod 400 and chown mongodb before starting mongod
#   * the first admin user must be created through the localhost exception -> mongosh runs inside
#     the container with docker exec
# Uses ports 27017-27019: stop the mini project and the Chapter 8 replica set first.
set -e
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../chapter-13"
for c in mongo-rs0-1 mongo-rs0-2 mongo-rs0-3; do docker rm -f "$c" >/dev/null 2>&1 || true; done
[ -f keyfile ] || { openssl rand -base64 756 > keyfile; echo "[OK] keyfile generated"; }
KF=$(pwd -W 2>/dev/null || pwd)/keyfile
docker network create prod-rs-net >/dev/null 2>&1 || true
for i in 1 2 3; do
  docker rm -f prod-mongo-$i >/dev/null 2>&1 || true
  docker run -d --name prod-mongo-$i --network prod-rs-net -p $((27016 + i)):27017 \
    -v "$KF:/tmp/keyfile:ro" -v prod_data$i:/data/db mongo:7 \
    bash -c 'cp /tmp/keyfile /etc/mongo-keyfile && chmod 400 /etc/mongo-keyfile && chown 999:999 /etc/mongo-keyfile && exec docker-entrypoint.sh mongod --replSet rs0 --bind_ip_all --auth --keyFile /etc/mongo-keyfile' >/dev/null
done
echo "Waiting for mongod..."
for i in $(seq 1 40); do docker exec prod-mongo-1 mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 1; done
m() { docker exec -i prod-mongo-1 mongosh --quiet "$@"; }

echo -e "\n=== Create admin user (localhost exception) ==="
m --eval 'db.getSiblingDB("admin").createUser({user:"admin",pwd:"AdminPass123!",roles:[{role:"root",db:"admin"}]}); print("[OK] admin created")' \
  || echo "(admin already exists)"
echo -e "\n=== Initiate the replica set ==="
m -u admin -p 'AdminPass123!' --authenticationDatabase admin --eval '
try { rs.initiate({_id:"rs0", members:[{_id:0,host:"prod-mongo-1:27017",priority:2},{_id:1,host:"prod-mongo-2:27017"},{_id:2,host:"prod-mongo-3:27017",arbiterOnly:true}]}); print("[OK] initiated") }
catch (e) { print("(" + e.codeName + ")") }'
echo "Waiting for the election..."; sleep 15
echo -e "\n=== Health ==="
m -u admin -p 'AdminPass123!' --authenticationDatabase admin --eval 'rs.status().members.forEach(x => print(x.name, x.stateStr, "health=" + x.health))'
echo -e "\n=== Unauthenticated access is refused ==="
m --eval 'try { rs.status(); print("[ERROR] allowed") } catch (e) { print("[OK] refused: " + e.codeName) }'
echo -e "\n[OK] Production replica set with keyFile authentication is running."
echo "Stop it with: docker rm -f prod-mongo-1 prod-mongo-2 prod-mongo-3"
