#!/bin/bash
set -o errexit
export TEST_USER="pn"

CONTAINER_NAME="application-server"

# Standard Workbench smoke tests (gcsfuse, wb CLI, fuse.conf).
bats tests/common/base.bats

# MDV-specific checks.
echo "# Checking MDV backend on port 5055"
timeout 60 docker exec --user root "$CONTAINER_NAME" bash -c '
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null http://localhost:5055/; then
      echo "MDV responded on 5055"
      exit 0
    fi
    sleep 2
  done
  echo "ERROR: MDV did not respond on port 5055"
  exit 1
'

echo "# Checking PostgreSQL backend is reachable from the app container"
docker exec --user root "$CONTAINER_NAME" bash -c '
  getent hosts mdv_db > /dev/null || { echo "ERROR: mdv_db not resolvable"; exit 1; }
  echo "mdv_db is reachable"
'
