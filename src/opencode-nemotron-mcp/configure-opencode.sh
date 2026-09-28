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
MODEL="${3:-$(OPENCODE_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/resolve-model.sh")}"
readonly SCRIPT_DIR MODEL
readonly CONFIG_DIR="${USER_HOME_DIR}/.config/opencode"
readonly CONFIG_FILE="${CONFIG_DIR}/opencode.json"
readonly CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
AVAILABLE_MODELS="$("${SCRIPT_DIR}/available-models.sh")"
readonly AVAILABLE_MODELS

if [[ ! "${CONTEXT_LENGTH}" =~ ^[1-9][0-9]*$ ]] || (( CONTEXT_LENGTH < 16384 )); then
  echo "OLLAMA_CONTEXT_LENGTH must be an integer of at least 16384 (65536 recommended)." >&2
  exit 1
fi

mkdir -p "${CONFIG_DIR}"

if [[ "${MODEL}" != "prompt" ]]; then
  IN_CATALOG="$(jq -r --arg model "${MODEL}" 'any(.tag == $model)' "${SCRIPT_DIR}/models.json")"
  IS_AVAILABLE="$(jq -r --arg model "${MODEL}" 'any(.tag == $model)' <<< "${AVAILABLE_MODELS}")"
  if [[ "${IN_CATALOG}" == "true" && "${IS_AVAILABLE}" != "true" ]]; then
    echo "${MODEL} is not available on this GPU. Run opencode-model --list for compatible models." >&2
    exit 1
  fi
fi

PROVIDER_MODELS="$(jq --argjson context "${CONTEXT_LENGTH}" \
  'reduce .[] as $entry ({}; .[$entry.tag] = {
    name: $entry.name,
    limit: {context: $context, output: 8192}
  })' <<< "${AVAILABLE_MODELS}")"

# Preserve explicit custom-tag support. Catalog models are filtered by VRAM;
# custom tags are an expert override and cannot be sized from local metadata.
if [[ "${MODEL}" != "prompt" ]] && ! jq -e --arg model "${MODEL}" 'has($model)' \
  <<< "${PROVIDER_MODELS}" > /dev/null; then
  PROVIDER_MODELS="$(jq --arg model "${MODEL}" --argjson context "${CONTEXT_LENGTH}" \
    '.[$model] = {name: $model, limit: {context: $context, output: 8192}}' \
    <<< "${PROVIDER_MODELS}")"
fi
readonly PROVIDER_MODELS

# share=disabled keeps prompts and code off opencode's hosted sharing service.
# autoupdate=false keeps the version pinned by the Dockerfile.
jq -n --arg model "${MODEL}" --arg home "${USER_HOME_DIR}" \
  --argjson models "${PROVIDER_MODELS}" '{
  "$schema": "https://opencode.ai/config.json",
  "model": ("ollama/" + $model),
  "small_model": ("ollama/" + $model),
  "autoupdate": false,
  "share": "disabled",
  "instructions": [($home + "/.claude/CLAUDE.md"), "/opt/opencode-workbench/workbench-instructions.md"],
  "mcp": {
    "wb": {
      "type": "local",
      "command": ["/opt/wb-mcp-server/wb-mcp-server"],
      "enabled": true,
      "timeout": 30000
    }
  },
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": $models
    }
  }
} | if $model == "prompt" then
  del(.model, .small_model) | .provider.ollama.models = {}
else . end' > "${CONFIG_FILE}.tmp"
mv "${CONFIG_FILE}.tmp" "${CONFIG_FILE}"

if [[ "$(id -u)" == "0" ]]; then
  chown "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/.config"
  chown -R "${USER_NAME}:${USER_NAME}" "${CONFIG_DIR}"
fi

echo "Wrote opencode config for ${MODEL} to ${CONFIG_FILE}"
