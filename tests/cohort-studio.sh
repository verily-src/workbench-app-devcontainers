#!/bin/bash
set -o errexit
set -o nounset

readonly CONTAINER_NAME="application-server"

echo "Running Cohort Studio smoke test"

docker exec "${CONTAINER_NAME}" pgrep -f uvicorn

readonly RESPONSE=$(docker exec "${CONTAINER_NAME}" \
    curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/health)

if [[ "${RESPONSE}" != "200" ]]; then
    echo "ERROR: /api/health returned ${RESPONSE}, expected 200"
    exit 1
fi

readonly FRONTEND=$(docker exec "${CONTAINER_NAME}" \
    curl -fsS http://localhost:8080/)
if [[ "${FRONTEND}" != *'<div id="root">'* ]]; then
    echo "ERROR: / did not return the Cohort Studio frontend"
    exit 1
fi

readonly VERSION=$(docker exec "${CONTAINER_NAME}" \
    curl -fsS http://localhost:8080/api/version)
readonly APP_SHA=$(docker exec "${CONTAINER_NAME}" python3 -c \
    'import json,sys; print(json.loads(sys.argv[1]).get("sha", ""))' \
    "${VERSION}")
if [[ -n "${EXPECTED_APP_SHA:-}" ]]; then
    if [[ "${APP_SHA}" != "${EXPECTED_APP_SHA}" ]]; then
        echo "ERROR: /api/version returned ${APP_SHA}, expected ${EXPECTED_APP_SHA}"
        exit 1
    fi
elif [[ "${APP_SHA}" != "unknown" && ! "${APP_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: /api/version returned an invalid SHA: ${VERSION}"
    exit 1
fi

echo "Cohort Studio smoke test passed"
