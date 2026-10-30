#!/bin/bash

# install-node.sh installs Node.js on the VM. Flatcar linux does not support package manager. So
# instead of installing node.js using package manager, we download the source code and extract it to
# /opt.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Download Node.js from the source code and extract it to /opt
NODE_VERSION="v24.20.0"
NODE_SHA256="855d581f8a4eb1a8117e3426de25fe02770592febcfb31369aee1ffbfee9e8ec"
NODE_SOURCE=""
CLI_VERSION=""
if [[ -f /home/core/dependency-lock.json ]]; then
  jq -e '.schema_version == 1 and .source_contract == 1' /home/core/dependency-lock.json >/dev/null
  NODE_VERSION="v$(jq -er '.host_versions.node' /home/core/dependency-lock.json)"
  NODE_SHA256=$(jq -er '.host_artifacts.node.sha256' /home/core/dependency-lock.json)
  NODE_SOURCE=$(jq -er '.host_artifacts.node.url' /home/core/dependency-lock.json)
  CLI_VERSION=$(jq -er '.host_versions.devcontainer_cli' /home/core/dependency-lock.json)
  [[ "${NODE_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && "${NODE_SHA256}" =~ ^[a-f0-9]{64}$ && "${NODE_SOURCE}" == https://* ]]
  jq -e '.host_artifacts.devcontainer_cli.package_json' /home/core/dependency-lock.json > /home/core/package.json
  jq -e '.host_artifacts.devcontainer_cli.package_lock_json' /home/core/dependency-lock.json > /home/core/package-lock.json
fi
readonly NODE_VERSION NODE_SHA256 NODE_SOURCE CLI_VERSION
readonly PLATFORM="linux-x64"
readonly NODE_TAR="node-${NODE_VERSION}-${PLATFORM}.tar.gz"
readonly NODE_INSTALL_SRC="${NODE_SOURCE:-https://storage.googleapis.com/bkt-workbench-artifacts/mirror/${NODE_TAR}}"
readonly NODE_INSTALL_PATH="/home/core/${NODE_TAR}"
readonly DEVCONTAINER_CLI_PATH="/home/core/node_modules/.bin/devcontainer"

# Reuse Node and the devcontainer CLI from an earlier boot.
if [[ "$(node --version 2>/dev/null)" == "${NODE_VERSION}" ]]; then
  echo "Node ${NODE_VERSION} is already installed; skipping download"
else
  echo "Downloading Node from ${NODE_INSTALL_SRC}"
  wget -q -O "${NODE_INSTALL_PATH}" "${NODE_INSTALL_SRC}"
  echo "${NODE_SHA256}  ${NODE_INSTALL_PATH}" | sha256sum -c

  echo "Installing Node from ${NODE_INSTALL_PATH}"
  tar -xzf "${NODE_INSTALL_PATH}" -C /opt --strip-components=1
  rm -f "${NODE_INSTALL_PATH}"
fi

if [[ -n "${CLI_VERSION}" ]]; then
  node /home/core/dependency-lock.mjs validate /home/core/dependency-lock.json
  node /home/core/dependency-lock.mjs apply-host /home/core/dependency-lock.json /home/core
fi

if [[ -x "${DEVCONTAINER_CLI_PATH}" && ( -z "${CLI_VERSION}" || "$("${DEVCONTAINER_CLI_PATH}" --version)" == "${CLI_VERSION}" ) ]]; then
  echo "Devcontainer CLI is already installed; skipping npm install"
else
  echo "Installing node packages"
  npm --prefix /home/core ci
fi

if [[ -n "${CLI_VERSION}" ]]; then
  [[ "$("${DEVCONTAINER_CLI_PATH}" --version)" == "${CLI_VERSION}" ]]
fi
