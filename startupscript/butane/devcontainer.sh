#!/bin/bash

# devcontainer.sh is a wrapper to run devcontainer.js.
# Note: this script requires the devcontainer.js to be installed in /home/core/package/devcontainer.js
# and Node to be installed on the VM.

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

export PATH="/opt/bin:$PATH"
readonly DEVCONTAINER="node /home/core/package/devcontainer.js"
readonly CMD="$1"
readonly FOLDER="$2"
if [[ "$CMD" == "build" ]]; then
    $DEVCONTAINER build --workspace-folder "${FOLDER}"
elif [[ "$CMD" == "up" ]]; then
    $DEVCONTAINER up --workspace-folder "${FOLDER}"
else
    echo "unknown command ${CMD}"
    exit 1
fi
