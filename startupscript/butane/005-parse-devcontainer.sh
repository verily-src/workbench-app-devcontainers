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
  echo "  container_image: the container image to use."
  echo "  container_port: the port to expose."
  exit 1
}

# Check that the required arguments are provided: devcontainer_path, cloud, login
if [[ $# -lt 3 ]]; then
    usage
fi

readonly DEVCONTAINER_PATH="$1"
readonly CLOUD="$2"
readonly LOGIN="$3"
readonly CONTAINER_IMAGE="${4:-debian:bullseye}"
readonly CONTAINER_PORT="${5:-8080}"

readonly DEVCONTAINER_CONFIG_PATH="${DEVCONTAINER_PATH}/.devcontainer.json"
readonly DEVCONTAINER_DOCKER_COMPOSE_PATH="${DEVCONTAINER_PATH}/docker-compose.yaml"

if [[ -d /home/core/devcontainer/startupscript ]]; then
    cp -r /home/core/devcontainer/startupscript "${DEVCONTAINER_PATH}"/startupscript
fi

replace_template_options() {
    local TEMPLATE_PATH="$1"

    echo "replacing templateOptions in ${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:login}|${LOGIN}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:cloud}|${CLOUD}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:containerImage}|${CONTAINER_IMAGE}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:containerPort}|${CONTAINER_PORT}|g" "${TEMPLATE_PATH}"
}

# Substitute template options in devcontainer.json and docker-compose.yaml
replace_template_options "${DEVCONTAINER_CONFIG_PATH}"
replace_template_options "${DEVCONTAINER_DOCKER_COMPOSE_PATH}"

echo "publishing devcontainer.json to metadata"
export PATH="/opt/bin:$PATH"
# shellcheck source=/dev/null
source /home/core/metadata-utils.sh
readonly JSONC_STRIP_COMMENTS=/home/core/jsoncStripComments.mjs
DEVCONTAINER_CUSTOMIZATIONS="$("${JSONC_STRIP_COMMENTS}" < "${DEVCONTAINER_CONFIG_PATH}" | jq -c .customizations.workbench)"
readonly DEVCONTAINER_CUSTOMIZATIONS
set_metadata "devcontainer/customizations" "${DEVCONTAINER_CUSTOMIZATIONS}"
