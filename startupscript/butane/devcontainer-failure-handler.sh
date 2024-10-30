#!/bin/bash

# devcontainer-failue-handler.sh terminates the devcontainer service if
# the service has failed 3 times.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly RETRY_COUNT=3
readonly RETRY_FILE="/tmp/devcontainer-failure-count"

# Log failure
echo "failed: $(date)" >> "${RETRY_FILE}"

# Check if number of retries have exceeded maximum
num_retries="$(wc -l < "${RETRY_FILE}")"
if [[ "${num_retries}" -ge "${RETRY_COUNT}" ]]; then
        # Log failure
        source /home/core/metadata-utils.sh
        set_metadata "startup_script/status" "ERROR"
        set_metadata "startup_script/message" "There was an error launching your custom container on the VM. Please try recreating the VM."

        # Stop the service
        systemctl stop devcontainer.service
fi