#!/usr/bin/env bash
# Lab 12.1 on a dedicated MongoDB container started WITH --auth, so the permission checks
# are really enforced. mongosh runs inside the container, which lets the first admin user be
# created through MongoDB's localhost exception. No ports are published - nothing clashes.
set -e
export MSYS_NO_PATHCONV=1
C=mongo-auth-lab
docker rm -f "$C" >/dev/null 2>&1 || true
echo "=== Starting $C (mongod --auth) ==="
docker run -d --name "$C" mongo:7 mongod --auth --bind_ip_all >/dev/null
for i in $(seq 1 30); do docker exec "$C" mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 1; done
sh() { docker exec -i "$C" mongosh --quiet "$@"; }

echo -e "\n=== Step 1: Create the admin user (localhost exception, no users exist yet) ==="
sh --eval 'db.getSiblingDB("admin").createUser({user:"admin", pwd:"AdminPass123!", roles:[
  {role:"userAdminAnyDatabase",db:"admin"},{role:"clusterAdmin",db:"admin"},{role:"readWriteAnyDatabase",db:"admin"}]});
  print("[OK] Admin user created.")'

echo -e "\n=== Step 2: Unauthenticated access is now refused ==="
sh --eval 'try { db.getSiblingDB("nosql_labs").test.findOne(); print("[ERROR] allowed") } catch (e) { print("[OK] refused: " + e.message.slice(0,60)) }'

echo -e "\n=== Step 3: Create application users and a custom role (as admin) ==="
sh -u admin -p 'AdminPass123!' --authenticationDatabase admin --eval '
const a = db.getSiblingDB("admin");
a.createUser({user:"analyst", pwd:"AnalystPass123!", roles:[{role:"read",db:"nosql_labs"},{role:"read",db:"bookstore"}]});
print("[OK] analyst      - read-only on nosql_labs, bookstore");
a.createUser({user:"app_writer", pwd:"WriterPass123!", roles:[{role:"readWrite",db:"nosql_labs"}]});
print("[OK] app_writer   - readWrite on nosql_labs");
a.createRole({role:"limitedWriter", privileges:[
  {resource:{db:"nosql_labs",collection:"logs"}, actions:["find","insert","update"]},
  {resource:{db:"nosql_labs",collection:""}, actions:["find"]}], roles:[]});
a.createUser({user:"log_writer", pwd:"LogPass123!", roles:[{role:"limitedWriter",db:"admin"}]});
print("[OK] log_writer   - custom role: insert/update on nosql_labs.logs, read the rest");
db.getSiblingDB("bookstore").books.insertOne({title:"Clean Code"});'

echo -e "\n=== Step 4: Test permission enforcement ==="
sh -u analyst -p 'AnalystPass123!' --authenticationDatabase admin --eval '
try { db.getSiblingDB("nosql_labs").test_col.insertOne({x:1}); print("[ERROR] analyst write allowed") }
catch (e) { print("[OK] analyst write rejected: " + e.message.slice(0,60)) }
print("[OK] analyst can read: " + db.getSiblingDB("bookstore").books.countDocuments() + " book(s)")'
sh -u app_writer -p 'WriterPass123!' --authenticationDatabase admin --eval '
try { db.getSiblingDB("bookstore").books.find().toArray(); print("[ERROR] read allowed") }
catch (e) { print("[OK] app_writer read of bookstore rejected: " + e.message.slice(0,60)) }
db.getSiblingDB("nosql_labs").orders.insertOne({ok:1}); print("[OK] app_writer can write nosql_labs")'
sh -u log_writer -p 'LogPass123!' --authenticationDatabase admin --eval '
db.getSiblingDB("nosql_labs").logs.insertOne({msg:"login"}); print("[OK] log_writer wrote to logs");
try { db.getSiblingDB("nosql_labs").orders.insertOne({x:1}); print("[ERROR] allowed") }
catch (e) { print("[OK] log_writer write to orders rejected: " + e.message.slice(0,60)) }'

echo -e "\n[OK] RBAC lab complete. Remove the container with: docker rm -f $C"
