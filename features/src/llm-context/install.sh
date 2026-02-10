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

# Options from devcontainer-feature.json
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

readonly AUTORUN="${AUTORUN:-"true"}"

echo "Installing LLM Context Generator for user: ${USERNAME} (home: ${USER_HOME_DIR})"

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

readonly LLM_CONTEXT_DIR="/opt/llm-context"
readonly GENERATE_SCRIPT="${LLM_CONTEXT_DIR}/generate-context.sh"
readonly SKILLS_DIR="${LLM_CONTEXT_DIR}/skills"

# Save the directory where the feature files are located
FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

echo "Starting LLM Context Generator installation..."

# Create installation directory
mkdir -p "${LLM_CONTEXT_DIR}"
mkdir -p "${SKILLS_DIR}"

# Copy the generate-context.sh script
cp "${FEATURE_DIR}/generate-context.sh" "${GENERATE_SCRIPT}"
chmod +x "${GENERATE_SCRIPT}"

# Copy skill files
if [[ -d "${FEATURE_DIR}/skills" ]]; then
    cp -r "${FEATURE_DIR}/skills/"* "${SKILLS_DIR}/" 2>/dev/null || true
fi

# Create user-specific directories
USER_WORKBENCH_DIR="${USER_HOME_DIR}/.workbench"
USER_SKILLS_DIR="${USER_WORKBENCH_DIR}/skills"
mkdir -p "${USER_WORKBENCH_DIR}"
mkdir -p "${USER_SKILLS_DIR}"

# Create a wrapper script that generates context with proper user context
cat > "${LLM_CONTEXT_DIR}/run-as-user.sh" << 'WRAPPER_EOF'
#!/bin/bash
# Wrapper to run generate-context.sh with proper environment
set -e

# Source user environment
if [[ -f ~/.bashrc ]]; then
    source ~/.bashrc 2>/dev/null || true
fi

# Run the generator
/opt/llm-context/generate-context.sh "$@"
WRAPPER_EOF
chmod +x "${LLM_CONTEXT_DIR}/run-as-user.sh"

# Copy skill files to user directory
cp -r "${SKILLS_DIR}/"* "${USER_SKILLS_DIR}/" 2>/dev/null || true

# Set ownership
chown -R "${USERNAME}:" "${LLM_CONTEXT_DIR}"
chown -R "${USERNAME}:" "${USER_WORKBENCH_DIR}"

# Add to bashrc for easy access
cat >> "${USER_HOME_DIR}/.bashrc" << 'BASHRC_EOF'

# LLM Context Generator
alias generate-llm-context='/opt/llm-context/generate-context.sh'
alias refresh-context='/opt/llm-context/generate-context.sh'
export LLM_CONTEXT_ENABLED=true
BASHRC_EOF

chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo ""
echo "=========================================="
echo "LLM Context Generator installation complete!"
echo "=========================================="
echo ""
echo "The context generator is installed at: ${GENERATE_SCRIPT}"
echo "Skills directory: ${USER_SKILLS_DIR}"
echo ""
if [[ "${AUTORUN}" == "true" ]]; then
    echo "Auto-run is ENABLED: Context will be generated on container start."
else
    echo "Auto-run is DISABLED: Run 'generate-llm-context' to generate context."
fi
echo ""
echo "After generation, Claude Code will auto-discover ~/CLAUDE.md"
echo "=========================================="
echo ""

echo "Done!"
