#!/usr/bin/env bash

# install.sh installs Gemini CLI in the devcontainer. Currently it only supports
# Debian-based systems (e.g. Ubuntu) on x86_64.

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

readonly GEMINI_INSTALL_DIR="/opt/gemini"

function cleanup() {
    rm -rf "${WORKDIR:?}"
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

echo "Starting Gemini CLI installation..."

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

# Install required packages
check_packages \
    ca-certificates \
    curl \
    git

# Check if Node.js is installed and version is >= 20 (required for Gemini CLI)
NODE_VERSION_REQUIRED=20
INSTALL_NODE=false

if ! command -v node &> /dev/null; then
    echo "Node.js is not installed. Installing Node.js 20..."
    INSTALL_NODE=true
else
    NODE_MAJOR_VERSION=$(node --version | cut -d'.' -f1 | sed 's/v//')
    if [ "$NODE_MAJOR_VERSION" -lt "$NODE_VERSION_REQUIRED" ]; then
        echo "Node.js version $NODE_MAJOR_VERSION detected, but Gemini CLI requires Node.js >= $NODE_VERSION_REQUIRED. Upgrading..."
        INSTALL_NODE=true
    fi
fi

if [ "$INSTALL_NODE" = true ]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

# Create installation directory
mkdir -p "${GEMINI_INSTALL_DIR}"

# Install Gemini CLI globally via npm
if [[ "${VERSION}" == "latest" ]]; then
    npm install -g @google/gemini-cli
else
    npm install -g "@google/gemini-cli@${VERSION}"
fi

# Create a symlink in /usr/local/bin if it doesn't exist
if ! command -v gemini &> /dev/null; then
    GEMINI_BIN="$(npm root -g)/@google/gemini-cli/bin/gemini"
    if [[ -f "${GEMINI_BIN}" ]]; then
        ln -sf "${GEMINI_BIN}" /usr/local/bin/gemini
    else
        # Alternative: try to find it in npm's bin directory
        NPM_BIN="$(npm bin -g)/gemini"
        if [[ -f "${NPM_BIN}" ]]; then
            ln -sf "${NPM_BIN}" /usr/local/bin/gemini
        else
            echo "Warning: Could not find gemini binary after npm installation"
        fi
    fi
fi

# Gemini CLI will create its config directory automatically when first run

# Make sure the login user is the owner of their .bashrc
chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo ""
echo "=========================================="
echo "Gemini CLI installation complete!"
echo "=========================================="
echo ""
if command -v gemini &> /dev/null; then
    echo "Gemini CLI is installed and available in PATH"
    gemini --version 2>/dev/null || echo "To use Gemini CLI, set your API key:"
    echo "  export GEMINI_API_KEY=your_api_key"
else
    echo "Warning: Gemini CLI was installed but not found in PATH"
fi
echo "=========================================="
echo ""

echo "Done!"
