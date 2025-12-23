#!/bin/bash
set -o errexit -o nounset -o pipefail -o xtrace

# ttyd feature install script
# Installs ttyd - a simple tool for sharing terminal over the web

readonly TTYD_VERSION="${VERSION:-"latest"}"
readonly TTYD_PORT="${PORT:-"7681"}"

echo "Installing ttyd ${TTYD_VERSION}..."

# Check for root
if [ "$(id -u)" -ne 0 ]; then
    echo 'Script must be run as root. Use sudo, su, or add "USER root" to your Dockerfile before running this script.'
    exit 1
fi

# Detect OS
. /etc/os-release
if [ "${ID}" = "debian" ] || [ "${ID_LIKE}" = "debian" ]; then
    ADJUSTED_ID="debian"
elif [[ "${ID}" = "rhel" || "${ID}" = "fedora" || "${ID_LIKE}" = *"rhel"* || "${ID_LIKE}" = *"fedora"* ]]; then
    ADJUSTED_ID="rhel"
else
    echo "Linux distro ${ID} not supported."
    exit 1
fi

# Install dependencies
if [ "${ADJUSTED_ID}" = "debian" ]; then
    apt-get update
    apt-get install -y --no-install-recommends curl ca-certificates
elif [ "${ADJUSTED_ID}" = "rhel" ]; then
    yum install -y curl ca-certificates
fi

# Determine architecture
ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64) ARCH="x86_64" ;;
    aarch64) ARCH="aarch64" ;;
    armv7l) ARCH="armv7" ;;
    *) echo "Unsupported architecture: ${ARCH}"; exit 1 ;;
esac

# Get latest version if needed
if [ "${TTYD_VERSION}" = "latest" ]; then
    TTYD_RELEASE_VERSION=$(curl -sL https://api.github.com/repos/tsl0922/ttyd/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "")
    # Fallback to a known version if API call fails
    if [ -z "${TTYD_RELEASE_VERSION}" ]; then
        echo "Warning: Could not fetch latest version from GitHub API, using fallback version 1.7.7"
        TTYD_RELEASE_VERSION="1.7.7"
    fi
else
    TTYD_RELEASE_VERSION="${TTYD_VERSION}"
fi

echo "Installing ttyd version ${TTYD_RELEASE_VERSION} for ${ARCH}..."

# Download and install ttyd
DOWNLOAD_URL="https://github.com/tsl0922/ttyd/releases/download/${TTYD_RELEASE_VERSION}/ttyd.${ARCH}"
curl -sL "${DOWNLOAD_URL}" -o /usr/local/bin/ttyd
chmod +x /usr/local/bin/ttyd

# Verify installation
if ! ttyd --version; then
    echo "Failed to install ttyd"
    exit 1
fi

# Clean up
if [ "${ADJUSTED_ID}" = "debian" ]; then
    rm -rf /var/lib/apt/lists/*
fi

echo "ttyd ${TTYD_RELEASE_VERSION} installed successfully!"
echo "Default port: ${TTYD_PORT}"
echo "To run: ttyd -p ${TTYD_PORT} bash"
