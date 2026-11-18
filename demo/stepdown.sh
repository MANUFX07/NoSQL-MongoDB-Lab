#!/usr/bin/env bash
# Chapter 8 demo: force the current primary to step down so the observer sees a failover.
export MSYS_NO_PATHCONV=1
echo "Stepping down the primary..."
docker exec mongo-rs0-1 mongosh --quiet --eval 'try { rs.stepDown(30) } catch (e) { print("(connection closed by step-down - expected)") }'
sleep 12
docker exec mongo-rs0-2 mongosh --port 27018 --quiet --eval 'rs.status().members.forEach(m => print(m.name, m.stateStr))'
