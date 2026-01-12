#!/bin/bash

# devcontainer.sh is a wrapper to run devcontainer cli.
# Note: this script requires Node and the package.json dependencies to be already installed.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function usage {
  echo "Usage: $0 <cmd> <workspace-folder>"
  echo "  build/up: either to build the devcontainer or start the devcontainer."
  echo "  path to the devcontainer folder."
  exit 1
}

if [[ $# -ne 2 ]]; then
    usage
fi

readonly DEVCONTAINER="npx --prefix /home/core devcontainer"
readonly CMD="$1"
readonly FOLDER="$2"
readonly FORCE_DEVCONTAINER_REBUILD_FILE="/tmp/force-devcontainer-rebuild"

if [[ "$CMD" == "build" ]]; then
    $DEVCONTAINER build --workspace-folder "${FOLDER}"
elif [[ "$CMD" == "up" ]]; then
    if [[ -f "${FORCE_DEVCONTAINER_REBUILD_FILE}" ]]; then
        echo "Forcing container rebuild due to configuration changes"
        $DEVCONTAINER up --workspace-folder "${FOLDER}" --remove-existing-container
        # Clean up indicator file after successful rebuild
        rm -f "${FORCE_DEVCONTAINER_REBUILD_FILE}"
    else
        echo "No configuration changes detected, reusing existing container if available"
        $DEVCONTAINER up --workspace-folder "${FOLDER}"
    fi
else
    echo "unknown command ${CMD}"
    exit 1
fi
