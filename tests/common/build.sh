#!/bin/bash

# build.sh
#
# Populates a devcontainer template with default values and runs a docker container
# with devcontainer CLI.
#
# Usage: build.sh <app>. The app templates must be located in src/ directory.

set -o errexit
set -o nounset

readonly TEMPLATE_ID="$1"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
readonly REPO_ROOT
readonly CLI_VERSION="${DEVCONTAINER_CLI_VERSION:-}"
if [[ -n "${CLI_VERSION}" && ! "${CLI_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "DEVCONTAINER_CLI_VERSION must be an exact version" >&2
    exit 2
fi

# include hidden files because devcontainer configs
# are in .devcontainer/ or .devcontainer.json file.
shopt -s dotglob

readonly SRC_DIR="/tmp/${TEMPLATE_ID}"
if [[ "${TEMPLATE_ID}" == dc-access-logging-app ]]; then
    export DC_ACCESS_ENV=test
fi
cp -LR "src/." "/tmp"

pushd "${SRC_DIR}"

# Configure templates only if `devcontainer-template.json` contains the `options` property.
OPTION_PROPERTY="$(jq -r '.options' devcontainer-template.json)"
readonly OPTION_PROPERTY

if [[ "${OPTION_PROPERTY}" != "" ]] && [[ "${OPTION_PROPERTY}" != "null" ]]; then
    OPTIONS=()
    while IFS= read -r line; do
        OPTIONS+=("$line")
    done < <(jq -r '.options | keys[]' devcontainer-template.json)
    readonly OPTIONS

    if [[ "${OPTIONS[0]}" != "" ]] && [[ "${OPTIONS[0]}" != "null" ]]; then
        echo "(!) Configuring template options for '${TEMPLATE_ID}'"
        for OPTION in "${OPTIONS[@]}"; do
            OPTION_KEY="\${templateOption:$OPTION}"
            OPTION_VALUE=$(jq -r ".options | .${OPTION} | .default" devcontainer-template.json)

            if [[ "${OPTION_VALUE}" == "" ]] || [[ "${OPTION_VALUE}" == "null" ]]; then
                echo "Template '${TEMPLATE_ID}' is missing a default value for option '${OPTION}'"
                exit 1
            fi

            echo "(!) Replacing '${OPTION_KEY}' with '${OPTION_VALUE}'"
            OPTION_VALUE_ESCAPED=$(sed -e 's/[]\/$*.^[]/\\&/g' <<<"${OPTION_VALUE}")
            find ./ -type f -print0 | xargs -0 sed -i "s/${OPTION_KEY}/${OPTION_VALUE_ESCAPED}/g"
        done
    fi
fi

popd

#########################
# Copy in features folder
#########################
mkdir -p "${SRC_DIR}/.devcontainer/features"
rsync -a --ignore-existing "features/src/" "${SRC_DIR}/.devcontainer/features"

############################
# Prefetch OCI features
############################
PREFETCH_SCRIPT="./startupscript/butane/prefetch-oci-features.sh"
if [[ -f "${SRC_DIR}/.devcontainer.json" ]]; then
    "${PREFETCH_SCRIPT}" "${SRC_DIR}/.devcontainer.json"
elif [[ -f "${SRC_DIR}/.devcontainer/devcontainer.json" ]]; then
    "${PREFETCH_SCRIPT}" "${SRC_DIR}/.devcontainer/devcontainer.json"
fi

############################
# Install Devcontainer CLI
############################
export DOCKER_BUILDKIT=1
export BUILDX_BAKE_ENTITLEMENTS_FS=0
echo "(*) Installing @devcontainer/cli"
if [[ -n "${CLI_VERSION}" ]]; then
    CLI_DIR="$(mktemp -d)"
    readonly CLI_DIR
    npm install --prefix "${CLI_DIR}" "@devcontainers/cli@${CLI_VERSION}"
else
    readonly CLI_DIR="${REPO_ROOT}/startupscript/butane"
    npm ci --prefix "${CLI_DIR}"
fi
export PATH="${CLI_DIR}/node_modules/.bin:${PATH}"
expected_cli="${CLI_VERSION:-$(jq -r '.packages["node_modules/@devcontainers/cli"].version' "${CLI_DIR}/package-lock.json")}"
[[ "$(devcontainer --version)" == "${expected_cli}" ]]

#################################
# Workbench application specific
# Creates docker network
#################################
docker network create -d bridge app-network

################################################
# Starts docker container using devcontainer CLI
################################################
echo "Building Dev Container"
readonly ID_LABEL="test-container=${TEMPLATE_ID}"
devcontainer up --id-label "${ID_LABEL}" --workspace-folder "${SRC_DIR}"
