#!/bin/bash

# parse-devcontainer.sh parses the devcontainer templates and sets template variables. config
# customizations are pushed to cloud metadata.

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

readonly DEVCONTAINER_CONFIG_PATH="${DEVCONTAINER_PATH}"/.devcontainer.json

if [[ -d /home/core/devcontainer/startupscript ]]; then
    cp -r /home/core/devcontainer/startupscript "${DEVCONTAINER_PATH}"/startupscript
fi
echo "replacing devcontainer.json templateOptions"
sed -i "s/\${templateOption:login}/${LOGIN}/g" "${DEVCONTAINER_CONFIG_PATH}"
sed -i "s/\${templateOption:cloud}/${CLOUD}/g" "${DEVCONTAINER_CONFIG_PATH}"

echo "publishing devcontainer.json to metadata"
export PATH="/opt/bin:$PATH"
# shellcheck source=/dev/null
source /home/core/metadata-utils.sh
readonly JSONC_STRIP_COMMENTS=/home/core/jsoncStripComments.mjs
DEVCONTAINER_CUSTOMIZATIONS=$(${JSONC_STRIP_COMMENTS} < "${DEVCONTAINER_CONFIG_PATH}" | jq -c .customizations.workbench)
readonly DEVCONTAINER_CUSTOMIZATIONS
set_metadata "devcontainer/customizations" "${DEVCONTAINER_CUSTOMIZATIONS}"
