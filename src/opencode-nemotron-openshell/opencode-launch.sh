#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
readonly SANDBOX_MODE_FILE="${OPENCODE_HOME:-/config}/.opencode-sandbox"

# Help and setup commands remain usable before choosing a model. Lifecycle
# hooks never prompt: only an interactive OpenCode launch invokes the picker.
case "${1:-}" in
  --help|-h|--version|-v|models|mcp|auth|debug|completion)
    exec /opt/opencode/.opencode/bin/opencode "$@"
    ;;
esac

# By default OpenCode runs in the OpenShell sandbox. "off" in
# /config/.opencode-sandbox (or OPENCODE_SANDBOX=off) runs it directly in this
# container, with the user's Workbench credentials and the Workbench MCP tools.
MODE="${OPENCODE_SANDBOX:-on}"
if [[ -s "${SANDBOX_MODE_FILE}" ]]; then
  MODE="$(tr -d '[:space:]' < "${SANDBOX_MODE_FILE}")"
fi

if [[ "${MODE}" != "off" ]]; then
  exec "${SCRIPT_DIR}/opencode-sandbox.sh" run "$@"
fi

echo "OpenCode is running outside the sandbox, with your Workbench credentials." >&2
if [[ "$("${SCRIPT_DIR}/resolve-model.sh")" == "prompt" ]]; then
  "${SCRIPT_DIR}/opencode-model.sh"
fi
exec /opt/opencode/.opencode/bin/opencode "$@"
