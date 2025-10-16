#!/bin/bash

# load-env.sh Loads environment variables for the attached AoU data collection
# version.
#
# Usage: source load-env.sh

# Get the environment variables inside a function so that the set -o options
# don't impact the user's environment, since this script needs to be sourced to
# apply the environment variables.
function get_env_vars() {
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

    local auth_token
    auth_token="$(wb auth print-access-token)"

    AUTH_TOKEN="$auth_token" ./load-env -workspace "${WORKSPACE_ID}" -wsm-url "${WSM_API_URL}"
}

ENV_VARS="$(get_env_file)"
ENV_VARS_RETVAL="$?"
readonly ENV_VARS
readonly ENV_VARS_RETVAL

# If get_env_vars fails, print the error message and exit.
if [ "${ENV_VARS_RETVAL}" -ne 0 ]; then
    echo "${ENV_VARS}"
    exit "${ENV_VARS_RETVAL}"
fi

eval "${ENV_VARS}"
