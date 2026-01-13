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
readonly CONTAINER_IMAGE="${5:-debian:bullseye}"
readonly CONTAINER_PORT="${6:-8080}"

readonly DEVCONTAINER_STARTUPSCRIPT_PATH='/home/core/devcontainer/startupscript'
readonly DEVCONTAINER_FEATURES_PATH='/home/core/devcontainer/features/src'
readonly NVIDIA_RUNTIME_PATH="${DEVCONTAINER_PATH}/startupscript/butane/nvidia-runtime.yaml"
readonly GPU_STATE_FILE="/home/core/gpu-state"
readonly FORCE_DEVCONTAINER_REBUILD_FILE="/tmp/force-devcontainer-rebuild"

if [[ -f "${DEVCONTAINER_PATH}/.devcontainer.json" ]]; then
  DEVCONTAINER_CONFIG_PATH="${DEVCONTAINER_PATH}/.devcontainer.json"
elif [[ -f "${DEVCONTAINER_PATH}/.devcontainer/devcontainer.json" ]]; then
  DEVCONTAINER_CONFIG_PATH="${DEVCONTAINER_PATH}/.devcontainer/devcontainer.json"
else
  echo "No devcontainer config file found." >&2
  exit 1
fi
readonly DEVCONTAINER_CONFIG_PATH

readonly DEVCONTAINER_DOCKER_COMPOSE_PATH="${DEVCONTAINER_PATH}/docker-compose.yaml"

# On first run, copy existing .devcontainer.json and docker-compose.yaml to template files
# On subsequent runs, the template files will be used to replace the original files
# so that if arguments change, they are properly applied to the original template files
if [[ ! -f "${DEVCONTAINER_CONFIG_PATH}.template" ]]; then
    cp "${DEVCONTAINER_CONFIG_PATH}" "${DEVCONTAINER_CONFIG_PATH}.template"
else
    cp "${DEVCONTAINER_CONFIG_PATH}.template" "${DEVCONTAINER_CONFIG_PATH}"
fi
if [[ -f "${DEVCONTAINER_DOCKER_COMPOSE_PATH}" ]]; then
  if [[ ! -f "${DEVCONTAINER_DOCKER_COMPOSE_PATH}.template" ]]; then
    cp "${DEVCONTAINER_DOCKER_COMPOSE_PATH}" "${DEVCONTAINER_DOCKER_COMPOSE_PATH}.template"
  else
    cp "${DEVCONTAINER_DOCKER_COMPOSE_PATH}.template" "${DEVCONTAINER_DOCKER_COMPOSE_PATH}"
  fi
fi

# Copy devcontainer post-startup scripts into the devcontainer folder so they
# can be accessed by the devcontainer.json, but avoid creating a subdirectory
# if the target directory already contains the files.
if [[ -d "${DEVCONTAINER_STARTUPSCRIPT_PATH}" ]]; then
    rsync -a --ignore-existing "${DEVCONTAINER_STARTUPSCRIPT_PATH}" "${DEVCONTAINER_PATH}"
fi

# Copy devcontainer features into the devcontainer folder, ignoring existing
# files.
if [[ -d "${DEVCONTAINER_FEATURES_PATH}" ]]; then
    mkdir -p "${DEVCONTAINER_PATH}/.devcontainer/features"
    # Append a trailing slash to the source path to ensure rsync copies the
    # contents rather than the directory itself.
    rsync -a --ignore-existing "${DEVCONTAINER_FEATURES_PATH}/" "${DEVCONTAINER_PATH}/.devcontainer/features"
fi

replace_template_options() {
    local TEMPLATE_PATH="$1"

    echo "replacing templateOptions in ${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:login}|${LOGIN}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:cloud}|${CLOUD}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:containerImage}|${CONTAINER_IMAGE}|g" "${TEMPLATE_PATH}"
    sed -i "s|\${templateOption:containerPort}|${CONTAINER_PORT}|g" "${TEMPLATE_PATH}"
}

detect_gpu() {
    # Detect NVIDIA GPUs
    if nvidia-smi > /dev/null 2>&1; then
        return 0  # GPU detected
    else
        return 1  # No GPU detected
    fi
}

handle_gpu_state_changed() {
    local current_state="$1"

    # If no previous state file exists, this is first run
    if [[ ! -f "${GPU_STATE_FILE}" ]]; then
        echo "${current_state}" > "${GPU_STATE_FILE}"
        echo "First run, GPU state: ${current_state} (0=present, 1=absent)"
        # Mark for rebuild on first run to ensure correct initial state
        touch "${FORCE_DEVCONTAINER_REBUILD_FILE}"
        return 0
    fi

    local previous_state
    previous_state="$(cat "${GPU_STATE_FILE}")"

    # Update the state file with current state
    echo "${current_state}" > "${GPU_STATE_FILE}"

    # Check if state changed
    if [[ "${current_state}" != "${previous_state}" ]]; then
        echo "GPU state changed from ${previous_state} to ${current_state} (0=present, 1=absent)"
        # Set marker to force container rebuild
        touch "${FORCE_DEVCONTAINER_REBUILD_FILE}"
    else
        echo "GPU state unchanged: ${current_state} (0=present, 1=absent)"
        # Clear marker if it exists
        rm -f "${FORCE_DEVCONTAINER_REBUILD_FILE}"
    fi
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
if [[ -f "${DEVCONTAINER_DOCKER_COMPOSE_PATH}" ]]; then
    replace_template_options "${DEVCONTAINER_DOCKER_COMPOSE_PATH}"
fi

gpu_exists=$(detect_gpu; echo $?)
handle_gpu_state_changed "${gpu_exists}"

# Apply GPU runtime configuration if GPU is present
if [[ "${gpu_exists}" == "0" ]]; then
    echo "NVIDIA GPU detected, applying GPU runtime configuration"
    apply_gpu_runtime "${DEVCONTAINER_DOCKER_COMPOSE_PATH}" "${NVIDIA_RUNTIME_PATH}"
else
    echo "No NVIDIA GPU detected, skipping GPU runtime configuration"
fi

echo 'publishing devcontainer.json to metadata'
# shellcheck source=/dev/null
source '/home/core/metadata-utils.sh'
readonly JSONC_STRIP_COMMENTS=/home/core/jsoncStripComments.mjs
DEVCONTAINER_CUSTOMIZATIONS="$("${JSONC_STRIP_COMMENTS}" < "${DEVCONTAINER_CONFIG_PATH}" | jq -c .customizations.workbench)"
readonly DEVCONTAINER_CUSTOMIZATIONS
set_metadata 'devcontainer/customizations' "${DEVCONTAINER_CUSTOMIZATIONS}"
