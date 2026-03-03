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

# Install Gemini CLI using official Google distribution
echo "Installing Gemini CLI from official source..."

# Download and install the official Gemini CLI
GEMINI_CLI_VERSION="${VERSION}"
if [ "${GEMINI_CLI_VERSION}" = "latest" ]; then
    GEMINI_CLI_VERSION="$(curl -s https://api.github.com/repos/google-gemini/gemini-cli/releases/latest | grep 'tag_name' | cut -d'"' -f4)"
fi

# Detect architecture
ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        ARCH="amd64"
        ;;
    aarch64|arm64)
        ARCH="arm64"
        ;;
    *)
        echo "Unsupported architecture: ${ARCH}"
        exit 1
        ;;
esac

# Download Gemini CLI binary
DOWNLOAD_URL="https://github.com/google-gemini/gemini-cli/releases/download/${GEMINI_CLI_VERSION}/gemini-cli_linux_${ARCH}"
echo "Downloading from: ${DOWNLOAD_URL}"

curl -fsSL "${DOWNLOAD_URL}" -o /usr/local/bin/gemini-cli
chmod +x /usr/local/bin/gemini-cli

# Verify installation
if ! command -v gemini-cli &> /dev/null; then
    echo "ERROR: Gemini CLI installation failed"
    exit 1
fi

echo "Gemini CLI installation completed successfully!"
echo "Users can now run 'gcloud ai' commands or use Gemini CLI tools."
