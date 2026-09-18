#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR

# Help and setup commands remain usable before choosing a model. Lifecycle
# hooks never prompt: only an interactive OpenCode launch invokes the picker.
case "${1:-}" in
  --help|-h|--version|-v|models|mcp|auth|debug|completion) ;;
  *)
    if [[ "$("${SCRIPT_DIR}/resolve-model.sh")" == "prompt" ]]; then
      "${SCRIPT_DIR}/opencode-model.sh"
    fi
    ;;
esac

exec /opt/opencode/.opencode/bin/opencode "$@"
