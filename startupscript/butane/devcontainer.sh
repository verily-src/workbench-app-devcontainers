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

export PATH="/opt/bin:$PATH"
readonly DEVCONTAINER="npx --prefix /home/core devcontainer"
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
