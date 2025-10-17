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

    if [ -f "${HOME}/.aou-env" ]; then
        cat "${HOME}/.aou-env"
        return 0
    fi

    CONTEXT_PATH="${HOME}/.workbench/context.json"
    readonly CONTEXT_PATH

    # Check if the context file exists.
    if [ ! -f "${CONTEXT_PATH}" ]; then
        echo "Unable to determine your current workspace. Has the workbench CLI been initialized?" >&2
        return 1
    fi

    WORKSPACE_ID="$(jq -r '.workspace.userFacingId' "${CONTEXT_PATH}")"
    readonly WORKSPACE_ID

    WSM_API_URL="$(jq -r '.server.workspaceManagerUri' "${CONTEXT_PATH}")"
    readonly WSM_API_URL

    if wb auth status 2>&1 | grep -q "NO USER LOGGED IN"; then
        echo "You are not logged in. Please run 'wb auth login' to log in." >&2
        return 1
    fi

    local auth_token
    auth_token="$(wb auth print-access-token)"

    ENV_VARS="$(AUTH_TOKEN="$auth_token" ./load-env -workspace "${WORKSPACE_ID}" -wsm-url "${WSM_API_URL}")"
    echo "${ENV_VARS}" > "${HOME}/.aou-env"
    echo "${ENV_VARS}"
}

ENV_VARS="$(get_env_vars)"
ENV_VARS_RETVAL="$?"
readonly ENV_VARS
readonly ENV_VARS_RETVAL

# If get_env_vars fails, print the error message and exit.
if [ "${ENV_VARS_RETVAL}" -ne 0 ]; then
    echo "${ENV_VARS}"
    return 1
fi

eval "${ENV_VARS}"
