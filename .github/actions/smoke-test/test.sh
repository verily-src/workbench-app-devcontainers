#!/bin/bash

# test.sh
#
# Runs test/test.sh in docker container using devcontainer exec.
# Usage: test.sh <app> where app templates are in src/. 

set -o errexit 
set -o nounset 

readonly TEMPLATE_ID="$1"
readonly TEST_USER="$2"
readonly WORKBENCH_TOOLS="$3"
readonly POSTGRES_CLIENT="$4"
readonly SRC_DIR="/tmp/${TEMPLATE_ID}"

echo "Running Smoke Test"

readonly ID_LABEL="test-container=${TEMPLATE_ID}"


# Suppressed expansion is intentional
# shellcheck disable=SC2016
SCRIPT="$(printf '\
    set -o errexit && \
    if [[ -f "test-project/test.sh" ]]; then \
      cd test-project && \
      if [[ "$(id -u)" == "0" ]]; then \
        chmod +x test.sh; \
      else \
        sudo chmod +x test.sh; \
      fi && \
      ./test.sh %q %q %q %q; \
    else \
      ls -a; \
    fi' "${TEMPLATE_ID}" "${TEST_USER}" "${WORKBENCH_TOOLS}" "${POSTGRES_CLIENT}")"
readonly SCRIPT

devcontainer exec \
  --workspace-folder "${SRC_DIR}" \
  --id-label "${ID_LABEL}" \
  /bin/bash -c "${SCRIPT}"

# Clean up
docker rm -f "$(docker container ls -f "label=${ID_LABEL}" -q)"
rm -rf "${SRC_DIR}"
