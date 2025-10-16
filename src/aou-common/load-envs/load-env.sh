#!/bin/bash

# load-env.sh Loads environment variables for the attached AoU data collection
# version.
#
# Usage: source load-env.sh

# Get the environment variable file inside a function so that the set -o options
# don't impact the user's environment, since this script needs to be sourced to
# apply the environment variables.
function get_env_file() {
    set -o errexit
    set -o nounset
    set -o pipefail

    CONTEXT_PATH="${HOME}/.workbench/context.json"
    readonly CONTEXT_PATH

    WORKSPACE_ID="$(jq -r '.workspace.userFacingId' "${CONTEXT_PATH}" || echo "")"
    while [ -z "${WORKSPACE_ID}" ]; do
      echo "Waiting for Workbench context to be set..."
      sleep 5
      WORKSPACE_ID="$(jq -r '.workspace.userFacingId' "${CONTEXT_PATH}" || echo "")"
    done
    readonly WORKSPACE_ID

    WSM_API_URL="$(jq -r '.server.workspaceManagerUri' "${CONTEXT_PATH}")"
    readonly WSM_API_URL

    export AUTH_TOKEN="$(wb auth print-access-token)"

    ENV_FILE="$(./load-env -workspace "${WORKSPACE_ID}" -wsm-url "${WSM_API_URL}" -envs ./.envs)"
    readonly ENV_FILE

    if [ ! -e "${ENV_FILE}" ]; then
        echo "Error: No environment variable file found at ${ENV_FILE}"
        exit 1
    fi

    echo "${ENV_FILE}"
}

ENV_FILE="$(get_env_file)"
ENV_FILE_RETVAL="$?"
readonly ENV_FILE
readonly ENV_FILE_RETVAL

# If get_env_file fails, print the error message and exit.
if [ "${ENV_FILE_RETVAL}" -ne 0 ]; then
    echo "${ENV_FILE}"
    exit "${ENV_FILE_RETVAL}"
fi

echo "Loading environment variables from ${ENV_FILE}"

set -o allexport
BASE_PATH="gs://test" source "${ENV_FILE}"
set +o allexport
