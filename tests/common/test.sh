#!/bin/bash

# test.sh
#
# Runs the per-app test script which invokes BATS test suites.
# Usage: test.sh <template_id>

set -o errexit
set -o nounset

readonly TEMPLATE_ID="$1"

echo "Running Smoke Test for ${TEMPLATE_ID}"

readonly TEST_SCRIPT="tests/${TEMPLATE_ID}.sh"
if [[ ! -f "${TEST_SCRIPT}" ]]; then
    echo "::error::No test script found at ${TEST_SCRIPT}"
    exit 1
fi

chmod +x "${TEST_SCRIPT}"
./"${TEST_SCRIPT}"

# Clean up
readonly ID_LABEL="test-container=${TEMPLATE_ID}"
docker rm -f "$(docker container ls -f "label=${ID_LABEL}" -q)" > /dev/null
rm -rf "/tmp/${TEMPLATE_ID}"
