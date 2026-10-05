#!/bin/bash
set -o errexit
set -o nounset

readonly CONTAINER_NAME="application-server"

echo "Running Cohort Dashboard smoke test"

# Verify the app process is running
docker exec "${CONTAINER_NAME}" pgrep -f "panel serve"

# Verify the Bokeh/Panel liveness endpoint responds
readonly RESPONSE=$(docker exec "${CONTAINER_NAME}" \
    curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/liveness)

if [[ "${RESPONSE}" != "200" ]]; then
    echo "ERROR: /liveness returned ${RESPONSE}, expected 200"
    exit 1
fi

echo "Cohort Dashboard smoke test passed"
