#!/usr/bin/env bash

# install.sh - Installs the LLM Context Generator for Workbench apps
#
# This feature generates a CLAUDE.md file that provides LLMs (like Claude Code)
# with context about the current Workbench workspace, resources, and tools.
# Claude Code auto-discovers ~/CLAUDE.md on startup.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Options from devcontainer-feature.json (converted to uppercase)
readonly USERNAME="${USERNAME:-"root"}"
USER_HOME_DIR="${USERHOMEDIR:-""}"
if [[ -z "${USER_HOME_DIR}" ]]; then
    if [[ "${USERNAME}" == "root" ]]; then
        USER_HOME_DIR="/root"
    else
        USER_HOME_DIR="/home/${USERNAME}"
    fi
fi
readonly USER_HOME_DIR

echo "Installing LLM Context Generator for user: ${USERNAME} (home: ${USER_HOME_DIR})"

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

readonly LLM_CONTEXT_DIR="/opt/llm-context"
readonly GENERATE_SCRIPT="${LLM_CONTEXT_DIR}/generate-context.sh"

# Save the directory where the feature files are located
FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

echo "Starting LLM Context Generator installation..."
echo "Feature directory: ${FEATURE_DIR}"

# Install jq if not present (required for JSON processing)
if ! command -v jq &> /dev/null; then
    echo "Installing jq..."
    if command -v apt-get &> /dev/null; then
        apt-get update && apt-get install -y --no-install-recommends jq
    elif command -v apk &> /dev/null; then
        apk add --no-cache jq
    else
        echo "WARNING: Could not install jq. Please install it manually."
    fi
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

# Add aliases and auto-run trigger to bashrc
cat >> "${USER_HOME_DIR}/.bashrc" << 'BASHRC_EOF'

# LLM Context Generator
export LLM_CONTEXT_ENABLED=true
alias generate-llm-context='/opt/llm-context/generate-context.sh'
alias refresh-context='/opt/llm-context/generate-context.sh'

# Auto-generate context on first interactive shell (if not already done)
if [[ -z "${LLM_CONTEXT_GENERATED:-}" ]] && [[ -f /opt/llm-context/run-context-generator.sh ]]; then
    export LLM_CONTEXT_GENERATED=1
    /opt/llm-context/run-context-generator.sh &
fi
BASHRC_EOF

chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc" 2>/dev/null || true

echo ""
echo "=========================================="
echo "LLM Context Generator installation complete!"
echo "=========================================="
echo ""
echo "Installed to: ${LLM_CONTEXT_DIR}"
echo "User home: ${USER_HOME_DIR}"
echo ""
echo "Context will auto-generate when:"
echo "  1. A terminal is opened (via .bashrc)"
echo "  2. You run 'generate-llm-context' or 'refresh-context'"
echo ""
echo "Claude Code will auto-discover ~/CLAUDE.md"
echo "=========================================="
echo ""

echo "Done!"
