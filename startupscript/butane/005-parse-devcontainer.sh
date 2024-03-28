#!/bin/bash

# parse-devcontainer.sh parses the devcontainer templates and sets template variables.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function usage {
  echo "Usage: $0 <path/to/devcontainer> <gcp/aws> <login>"
  echo "  devcontainer_path: folder directory of the devcontainer."
  echo "  cloud: gcp or aws."
  echo "  login: whether the user is logged into the workbench on startup."
  exit 1
}

if [[ $# -ne 3 ]]; then
    usage
fi

readonly DEVCONTAINER_PATH="$1"
readonly CLOUD="$2"
readonly LOGIN="$3"

if [[ -d /home/core/devcontainer/startupscript ]]; then
    cp -r /home/core/devcontainer/startupscript "${DEVCONTAINER_PATH}"/startupscript
fi
echo "replacing devcontainer.json templateOptions"
sed -i "s/\${templateOption:login}/${LOGIN}/g" "${DEVCONTAINER_PATH}"/.devcontainer.json
sed -i "s/\${templateOption:cloud}/${CLOUD}/g" "${DEVCONTAINER_PATH}"/.devcontainer.json
