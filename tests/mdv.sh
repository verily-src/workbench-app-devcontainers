#!/bin/bash
set -o errexit
export TEST_USER="pn"

CONTAINER_NAME="application-server"

# Standard Workbench smoke tests (gcsfuse, wb CLI, fuse.conf).
bats tests/common/base.bats

# MDV-specific checks.
echo "# Checking MDV on port 5055 (through nginx)"
# shellcheck disable=SC2016 # expands inside the container
timeout 120 docker exec --user root "$CONTAINER_NAME" bash -c '
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null http://localhost:5055/projects; then
      echo "MDV responded on 5055"
      exit 0
    fi
    sleep 2
  done
  echo "ERROR: MDV did not respond on port 5055"
  exit 1
'

echo "# Checking cross-origin isolation headers on the MDV document"
# shellcheck disable=SC2016 # expands inside the container
docker exec --user root "$CONTAINER_NAME" bash -c '
  headers="$(curl -fsS -D - -o /dev/null http://localhost:5055/)"
  echo "${headers}" | grep -qi "^Document-Isolation-Policy: isolate-and-credentialless" \
    || { echo "ERROR: Document-Isolation-Policy missing or wrong"; echo "${headers}"; exit 1; }
  echo "${headers}" | grep -qi "^Cross-Origin-Embedder-Policy: credentialless" \
    || { echo "ERROR: Cross-Origin-Embedder-Policy missing or wrong"; echo "${headers}"; exit 1; }
  [[ "$(echo "${headers}" | grep -ci "^Cross-Origin-Embedder-Policy:")" == 1 ]] \
    || { echo "ERROR: duplicate Cross-Origin-Embedder-Policy headers"; exit 1; }
  echo "isolation headers OK"
'

echo "# Checking PostgreSQL backend is reachable from the app container"
docker exec --user root "$CONTAINER_NAME" bash -c '
  getent hosts mdv_db > /dev/null || { echo "ERROR: mdv_db not resolvable"; exit 1; }
  echo "mdv_db is reachable"
'

echo "# Checking the sample project is shown when no workspace bucket has MDV data"
# shellcheck disable=SC2016 # expands inside the container
timeout 300 docker exec --user root "$CONTAINER_NAME" bash -c '
  for _ in $(seq 1 60); do
    if curl -fsS http://localhost:5055/projects | grep -q "sample--pbmc3k-processed"; then
      echo "sample project registered"
      exit 0
    fi
    sleep 5
  done
  echo "ERROR: sample project not registered"
  tail -30 /var/lib/mdv-workspace-sync/sync.log
  exit 1
'
