#!/bin/bash

# devcontainer-failue-handler.sh terminates the devcontainer service if
# the service has failed 3 times.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function usage {
  echo "Usage: $0 <shutdown_on_failure>"
  echo "  shutdown_on_failure: whether to shut down the system after running out of retries."
  exit 1
}

# Check that the required arguments are provided: shutdown_on_failure
if [[ $# -lt 1 ]]; then
    usage
fi

readonly SHUTDOWN_ON_FAILURE="$1"
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
        error_message=$(get_guest_attribute "startup_script/message" "")
        if [[ -z "${error_message}" ]]; then
          set_metadata "startup_script/message" "There was an error launching your custom container on the VM. Please try recreating the VM."
        fi
        # Stop the service
        systemctl stop devcontainer.service

        if [[ "$SHUTDOWN_ON_FAILURE" == "true" ]]; then
            # Sleep for a bit in case logs need to be captured
            sleep 10
            systemctl poweroff
        fi
fi
