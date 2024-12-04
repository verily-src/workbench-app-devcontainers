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
  echo "  accelerator: the accelerator to use. E.g: nvidia"
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
readonly ACCELERATOR="$4"
readonly CONTAINER_IMAGE="${5:-debian:bullseye}"
readonly CONTAINER_PORT="${6:-8080}"

readonly DEVCONTAINER_STARTUPSCRIPT_PATH='/home/core/devcontainer/startupscript'
readonly NVIDIA_RUNTIME_PATH="${DEVCONTAINER_PATH}/startupscript/butane/nvidia-runtime.yaml"

readonly DEVCONTAINER_CONFIG_PATH="${DEVCONTAINER_PATH}/.devcontainer.json"
readonly DEVCONTAINER_DOCKER_COMPOSE_PATH="${DEVCONTAINER_PATH}/docker-compose.yaml"

# On first run, copy existing .devcontainer.json and docker-compose.yaml to template files
# On subsequent runs, the template files will be used to replace the original files
# so that if arguments change, they are properly applied to the original template files
if [[ ! -f "${DEVCONTAINER_CONFIG_PATH}.template" ]]; then
    cp "${DEVCONTAINER_CONFIG_PATH}" "${DEVCONTAINER_CONFIG_PATH}.template"
else
    cp "${DEVCONTAINER_CONFIG_PATH}.template" "${DEVCONTAINER_CONFIG_PATH}"
fi
if [[ ! -f "${DEVCONTAINER_DOCKER_COMPOSE_PATH}.template" ]]; then
    cp "${DEVCONTAINER_DOCKER_COMPOSE_PATH}" "${DEVCONTAINER_DOCKER_COMPOSE_PATH}.template"
else
    cp "${DEVCONTAINER_DOCKER_COMPOSE_PATH}.template" "${DEVCONTAINER_DOCKER_COMPOSE_PATH}"
fi

# Copy devcontainer post-startup scripts into the devcontainer folder so they
# can be accessed by the devcontainer.json, but avoid creating a subdirectory
# if the target directory already contains the files.
if [[ -d "${DEVCONTAINER_STARTUPSCRIPT_PATH}" ]]; then
    rsync -a --ignore-existing "${DEVCONTAINER_STARTUPSCRIPT_PATH}" "${DEVCONTAINER_PATH}"
fi

replace_template_options() {
    local TEMPLATE_PATH="$1"

    echo "replacing templateOptions in ${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:login}|${LOGIN}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:cloud}|${CLOUD}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:containerImage}|${CONTAINER_IMAGE}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:containerPort}|${CONTAINER_PORT}|g" "${TEMPLATE_PATH}"
}

apply_gpu_runtime() {
    local DOCKER_COMPOSE_PATH="$1"
    local GPU_RUNTIME_BLOCK_PATH="$2"
    local TEMP_COMPOSE_PATH="${DOCKER_COMPOSE_PATH}.tmp"

    echo "Applying GPU runtime configuration in ${DOCKER_COMPOSE_PATH}"

    # Use awk to insert the GPU runtime block after the "app:" line in the docker-compose.yaml file
    awk -v gpu_config_path="$GPU_RUNTIME_BLOCK_PATH" '
    /^[[:space:]]*app:/ {                 # Match the line containing "app:" (can be indented)
        print $0;                         # Print the "app:" line as-is
        system("cat " gpu_config_path);   # Insert the GPU runtime block by reading from the specified file
    }
    {
        print $0;                         # For all other lines, print them unchanged
    }
    ' "${DOCKER_COMPOSE_PATH}" > "${TEMP_COMPOSE_PATH}"  # Redirect output to a temporary file

    # Replace the original docker-compose.yaml file with the modified temporary file
    mv "${TEMP_COMPOSE_PATH}" "${DOCKER_COMPOSE_PATH}"
}

# Substitute template options in devcontainer.json and docker-compose.yaml
replace_template_options "${DEVCONTAINER_CONFIG_PATH}"
replace_template_options "${DEVCONTAINER_DOCKER_COMPOSE_PATH}"

# apply gpu runtime block if accelerator is nvidia and cloud is gcp
if [[ "${ACCELERATOR}" == "nvidia" && "${CLOUD}" == "gcp" ]]; then
    apply_gpu_runtime "${DEVCONTAINER_DOCKER_COMPOSE_PATH}" "${NVIDIA_RUNTIME_PATH}"
fi

echo 'publishing devcontainer.json to metadata'
export PATH="/opt/bin:$PATH"
# shellcheck source=/dev/null
source '/home/core/metadata-utils.sh'
readonly JSONC_STRIP_COMMENTS=/home/core/jsoncStripComments.mjs
DEVCONTAINER_CUSTOMIZATIONS="$("${JSONC_STRIP_COMMENTS}" < "${DEVCONTAINER_CONFIG_PATH}" | jq -c .customizations.workbench)"
readonly DEVCONTAINER_CUSTOMIZATIONS
set_metadata 'devcontainer/customizations' "${DEVCONTAINER_CUSTOMIZATIONS}"
