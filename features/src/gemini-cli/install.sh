#!/usr/bin/env bash

# install.sh installs the Gemini CLI in the devcontainer

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly VERSION="${VERSION:-"latest"}"
readonly USERNAME="${USERNAME:-"root"}"
USER_HOME_DIR="${USERHOMEDIR:-"/home/${USERNAME}"}"
if [[ "${USER_HOME_DIR}" == "/home/root" ]]; then
    USER_HOME_DIR="/root"
fi
readonly USER_HOME_DIR

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

WORKDIR="$(mktemp -d)"
readonly WORKDIR

function cleanup() {
    rm -rf "${WORKDIR:?}"
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

echo "Starting Gemini CLI installation..."

# Install dependencies (curl, unzip, etc.)
check_packages curl ca-certificates

# Install Gemini CLI via npm (Google's official CLI package)
# Official package: @google/gemini-cli
# Requires: Node.js (should be installed via node feature in devcontainer.json)

if ! command -v npm &> /dev/null; then
    echo "ERROR: npm not found. Node.js is required for Gemini CLI installation."
    echo "Add 'ghcr.io/devcontainers/features/node' to your devcontainer features."
    exit 1
fi

echo "Node.js detected: $(node --version)"
echo "Installing Gemini CLI globally..."
npm install -g @google/gemini-cli

# Make it accessible to the specified user
if [ "${USERNAME}" != "root" ]; then
    chown -R "${USERNAME}:${USERNAME}" "$(npm root -g)" 2>/dev/null || true
fi

# Verify installation
if ! npm list -g @google/gemini-cli &> /dev/null; then
    echo "WARNING: Gemini CLI installation may have issues, but continuing..."
fi

echo "Gemini CLI installation completed successfully!"
echo "Users can now run 'gcloud ai' commands or use Gemini CLI tools."
