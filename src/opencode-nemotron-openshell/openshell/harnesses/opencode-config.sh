#!/bin/bash

# Config hook for the opencode harness (harnesses/opencode.yaml). Runs in the
# app, prints OpenCode's JSON config, and the framework passes it into the
# sandbox as OPENCODE_CONFIG_CONTENT. Local Ollama only, no MCP servers, no
# sharing or updates, and no web fetches (the policy would block them anyway).
#
# Input, from the framework's environment: OLLAMA_BASE_URL, AGENT_MODEL,
# AGENT_CONTEXT_LENGTH.

set -o errexit
set -o nounset
set -o pipefail

APP_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.."
readonly APP_DIR
readonly MODEL="${AGENT_MODEL:?AGENT_MODEL is not set}"
readonly URL="${OLLAMA_BASE_URL:?OLLAMA_BASE_URL is not set}"
readonly CONTEXT="${AGENT_CONTEXT_LENGTH:?AGENT_CONTEXT_LENGTH is not set}"

# Every compatible catalog model, so OpenCode's /model picker can't select one
# that is too large for the GPU.
models="$(jq --argjson context "${CONTEXT}" \
  'reduce .[] as $entry ({}; .[$entry.tag] = {
    name: $entry.name,
    limit: {context: $context, output: 8192}
  })' <<< "$("${APP_DIR}/available-models.sh")")"
if ! jq -e --arg model "${MODEL}" 'has($model)' <<< "${models}" > /dev/null; then
  models="$(jq --arg model "${MODEL}" --argjson context "${CONTEXT}" \
    '.[$model] = {name: $model, limit: {context: $context, output: 8192}}' <<< "${models}")"
fi

jq -nc --arg model "${MODEL}" --arg url "${URL}" --argjson models "${models}" '{
  "$schema": "https://opencode.ai/config.json",
  "model": ("ollama/" + $model),
  "small_model": ("ollama/" + $model),
  "enabled_providers": ["ollama"],
  "autoupdate": false,
  "share": "disabled",
  "instructions": ["/opt/opencode-sandbox/instructions.md"],
  "permission": {"webfetch": "deny"},
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {"baseURL": $url},
      "models": $models
    }
  }
}'
