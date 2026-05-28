#!/bin/bash
set -o errexit
set -o nounset

readonly CONTAINER_NAME="application-server"

echo "Running Cohort Explorer smoke test"

# Verify the app process is running
docker exec "${CONTAINER_NAME}" pgrep -f uvicorn

# Verify the health endpoint responds
readonly RESPONSE=$(docker exec "${CONTAINER_NAME}" \
    curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/health)

if [[ "${RESPONSE}" != "200" ]]; then
    echo "ERROR: /api/health returned ${RESPONSE}, expected 200"
    exit 1
fi

echo "Cohort Explorer smoke test passed"
