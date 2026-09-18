#!/bin/bash

# Writes the opencode global config so the agent talks to the local Ollama
# server instead of a hosted provider. Called from post-startup and on restart.

set -o errexit
set -o nounset
set -o pipefail

USER_NAME="${1:-}"
USER_HOME_DIR="${2:-}"

if [[ -z "${USER_NAME}" || -z "${USER_HOME_DIR}" ]]; then
  echo "Usage: $0 <username> <user-home-dir>"
  exit 1
fi

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
MODEL="$("${SCRIPT_DIR}/resolve-model.sh")"
readonly SCRIPT_DIR MODEL
readonly CONFIG_DIR="${USER_HOME_DIR}/.config/opencode"
readonly CONFIG_FILE="${CONFIG_DIR}/opencode.json"

mkdir -p "${CONFIG_DIR}"

# share=disabled keeps prompts and code off opencode's hosted sharing service.
# autoupdate=false keeps the version pinned by the Dockerfile.
jq -n --arg model "${MODEL}" '{
  "$schema": "https://opencode.ai/config.json",
  "model": ("ollama/" + $model),
  "small_model": ("ollama/" + $model),
  "autoupdate": false,
  "share": "disabled",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": { ($model): { "name": $model } }
    }
  }
}' > "${CONFIG_FILE}"

chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/.config"

echo "Wrote opencode config for ${MODEL} to ${CONFIG_FILE}"
