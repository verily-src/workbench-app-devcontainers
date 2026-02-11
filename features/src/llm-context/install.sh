#!/usr/bin/env bash

# install.sh installs the LLM Context Generator in the devcontainer.
# This feature generates a CLAUDE.md file that provides LLMs (like Claude Code)
# with context about the current Workbench workspace, resources, and tools.
# Claude Code auto-discovers ~/CLAUDE.md on startup.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Options from devcontainer-feature.json (converted to uppercase)
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

readonly LLM_CONTEXT_DIR="/opt/llm-context"
readonly GENERATE_SCRIPT="${LLM_CONTEXT_DIR}/generate-context.sh"

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

echo "Starting LLM Context Generator installation..."
echo "User: ${USERNAME}, Home: ${USER_HOME_DIR}"

# Save the directory where the feature files are located
FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

# Check for supported package manager
if type apt-get &>/dev/null; then
    # Install jq if not present (required for JSON processing)
    check_packages jq
elif type apk &>/dev/null; then
    # Alpine Linux
    apk add --no-cache jq
else
    echo "Warning: Could not install jq. Please install it manually."
fi

# Create installation directory
mkdir -p "${LLM_CONTEXT_DIR}"

# Copy the generate-context.sh script
if [[ -f "${FEATURE_DIR}/generate-context.sh" ]]; then
    cp "${FEATURE_DIR}/generate-context.sh" "${GENERATE_SCRIPT}"
    chmod +x "${GENERATE_SCRIPT}"
    echo "Copied generate-context.sh to ${GENERATE_SCRIPT}"
else
    echo "ERROR: generate-context.sh not found in ${FEATURE_DIR}"
    ls -la "${FEATURE_DIR}/"
    exit 1
fi

# Create user-specific directories
USER_WORKBENCH_DIR="${USER_HOME_DIR}/.workbench"
USER_SKILLS_DIR="${USER_WORKBENCH_DIR}/skills"
mkdir -p "${USER_WORKBENCH_DIR}"
mkdir -p "${USER_SKILLS_DIR}"

# Create a wrapper script that runs with proper user context
cat > "${LLM_CONTEXT_DIR}/run-context-generator.sh" << WRAPPER_EOF
#!/bin/bash
# Wrapper to run generate-context.sh with proper environment
# This script is called on container start

# Only run if we have a workspace set
if command -v wb &> /dev/null && wb workspace describe &> /dev/null; then
    echo "Generating LLM context..."
    ${GENERATE_SCRIPT} || echo "LLM context generation failed (non-fatal)"
else
    echo "Skipping LLM context generation: workspace not set or wb not available"
    echo "Run 'wb workspace set <workspace-id>' then 'generate-llm-context' manually"
fi
WRAPPER_EOF
chmod +x "${LLM_CONTEXT_DIR}/run-context-generator.sh"

# Set ownership
chown -R "${USERNAME}:" "${LLM_CONTEXT_DIR}" 2>/dev/null || true
chown -R "${USERNAME}:" "${USER_WORKBENCH_DIR}" 2>/dev/null || true

# Add aliases and environment to bashrc (context generation is triggered by postStartCommand, not bashrc)
{
    echo ""
    echo "# LLM Context Generator"
    echo "export LLM_CONTEXT_ENABLED=true"
    echo "export LLM_CONTEXT_HOME=\"${USER_HOME_DIR}\""
    echo "alias generate-llm-context='${GENERATE_SCRIPT} ${USER_HOME_DIR}'"
    echo "alias refresh-context='${GENERATE_SCRIPT} ${USER_HOME_DIR}'"
} >> "${USER_HOME_DIR}/.bashrc"

# Make sure the login user is the owner of their .bashrc
chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc" 2>/dev/null || true

echo ""
echo "=========================================="
echo "LLM Context Generator installation complete!"
echo "=========================================="
echo ""
echo "Installed to: ${LLM_CONTEXT_DIR}"
echo "User home: ${USER_HOME_DIR}"
echo ""
echo "Context will be generated via postStartCommand after startup completes."
echo "Manual refresh: run 'generate-llm-context' or 'refresh-context'"
echo ""
echo "Claude Code will auto-discover ~/CLAUDE.md"
echo "=========================================="
echo ""

echo "Done!"
