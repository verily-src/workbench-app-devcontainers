#!/bin/bash

# The `opencode` command: always starts the agent inside the OpenShell sandbox.
# This framework has no unsandboxed mode.

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR

# Version and help print text and start no agent.
case "${1:-}" in
  --help|-h|--version|-v)
    exec /opt/opencode/.opencode/bin/opencode "$@"
    ;;
esac

# Only an interactive launch invokes the model picker.
if [[ "$("${SCRIPT_DIR}/resolve-model.sh")" == "prompt" ]]; then
  "${SCRIPT_DIR}/opencode-model.sh"
fi

exec "${SCRIPT_DIR}/agent-sandbox.sh" run "$@"
