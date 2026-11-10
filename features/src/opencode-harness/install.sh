#!/usr/bin/env bash

# install.sh installs the opencode-harness feature: the OpenCode harness files into the
# agent-sandbox feature's harnesses/ folder, and the `opencode` command. See README.md.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly USERNAME="${USERNAME:-"root"}"
readonly INSTALL_LAUNCHER="${INSTALLLAUNCHER:-"true"}"

readonly SANDBOX_DIR="/opt/agent-sandbox"
readonly HARNESS_DIR="${SANDBOX_DIR}/harnesses"
readonly INSTALL_DIR="/opt/opencode-harness"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

echo "Starting opencode-harness installation..."

if [[ ! -x "${SANDBOX_DIR}/agent-sandbox.sh" ]]; then
    echo "Error: the agent-sandbox feature must be installed first (${SANDBOX_DIR} is missing)."
    exit 1
fi

# The harness files, where agent-sandbox looks for them. The hook runs where agent-sandbox runs.
mkdir -p "${HARNESS_DIR}"
cp "${FEATURE_DIR}"/harnesses/*.yaml "${FEATURE_DIR}"/harnesses/*.sh "${HARNESS_DIR}/"
chmod +x "${HARNESS_DIR}"/*.sh
# The default harness, unless another harness feature set one.
if [[ ! -s "${HARNESS_DIR}/default" ]]; then
    echo opencode > "${HARNESS_DIR}/default"
fi

if [[ "${INSTALL_LAUNCHER}" == "true" ]]; then
    mkdir -p "${INSTALL_DIR}"
    cp "${FEATURE_DIR}/opencode-launch.sh" "${INSTALL_DIR}/"
    chmod +x "${INSTALL_DIR}/opencode-launch.sh"
    ln -sf "${INSTALL_DIR}/opencode-launch.sh" /usr/local/bin/opencode
fi

echo "opencode-harness installed: harnesses in ${HARNESS_DIR} (default: $(cat "${HARNESS_DIR}/default")), user ${USERNAME}"
echo "Done!"
