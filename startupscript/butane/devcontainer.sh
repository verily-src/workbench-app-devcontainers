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
if [[ "$CMD" == "build" ]]; then
    # A restart reuses the existing container; rebuilding needs registry access.
    if [[ -n "$(docker ps -aq --filter "label=devcontainer.local_folder=${FOLDER}")" ]]; then
        echo "Devcontainer already exists; skipping build"
    else
        $DEVCONTAINER build --workspace-folder "${FOLDER}"
    fi
elif [[ "$CMD" == "up" ]]; then
    $DEVCONTAINER up --workspace-folder "${FOLDER}"
else
    echo "unknown command ${CMD}"
    exit 1
fi
