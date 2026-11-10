#!/usr/bin/env bash

# install.sh installs the ai-policy feature: the policy compiler in /opt/ai-policy.
# See README.md.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

readonly INSTALL_DIR="/opt/ai-policy"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

function cleanup() {
    rm -rf /var/lib/apt/lists/*
}

trap 'cleanup' EXIT

function apt_get_update() {
    if [ "$(find /var/lib/apt/lists/* | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update -y
    fi
}

# Checks if packages are installed and installs them if not
function check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update
        apt-get -y install --no-install-recommends "$@"
    fi
}

echo "Starting ai-policy installation..."

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

# The compiler is Python with PyYAML; workspace-data.py reads Workbench with urllib.
check_packages ca-certificates python3 python3-yaml

mkdir -p "${INSTALL_DIR}"
cp "${FEATURE_DIR}"/ai_policy.py "${FEATURE_DIR}"/render-policy.py "${FEATURE_DIR}"/workspace-data.py "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}"/*.py

echo "ai-policy installed in ${INSTALL_DIR}"
echo "Done!"
