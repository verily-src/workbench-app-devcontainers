#!/bin/bash
set -o errexit
set -o nounset

export BACKEND_CONTAINER="application-server"
export APP_ORIGIN="application-server:8080"

echo "Running Cohort Studio in a Virtual Browser smoke test"

bash tests/cohort-studio.sh

CHROME_CLI=$(docker exec browser printenv CHROME_CLI)
if [[ "${CHROME_CLI}" != "--kiosk http://${APP_ORIGIN}" ]]; then
    echo "ERROR: Chromium target does not match the allowed Studio origin"
    exit 1
fi

BROWSER_FRONTEND=$(docker exec browser curl -fsS --max-time 10 "http://${APP_ORIGIN}/")
if [[ "${BROWSER_FRONTEND}" != *'<div id="root">'* ]]; then
    echo "ERROR: browser container cannot fetch the Studio frontend"
    exit 1
fi

bats tests/common/virtual-browser.bats
