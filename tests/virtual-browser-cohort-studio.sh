#!/bin/bash
set -o errexit
set -o nounset

export BACKEND_CONTAINER="application-server"
export APP_ORIGIN="application-server:8080"

echo "Running Cohort Studio in a Virtual Browser smoke test"

# Verify the app process is running
docker exec "${BACKEND_CONTAINER}" pgrep -f uvicorn

# Verify the health endpoint responds
RESPONSE=$(docker exec "${BACKEND_CONTAINER}" \
    curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/health)
readonly RESPONSE

if [[ "${RESPONSE}" != "200" ]]; then
    echo "ERROR: /api/health returned ${RESPONSE}, expected 200"
    exit 1
fi

bats tests/common/virtual-browser.bats
