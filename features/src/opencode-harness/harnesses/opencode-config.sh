#!/bin/bash

# Config hook for the opencode harness: prints OpenCode's JSON config, which agent-sandbox
# passes into the sandbox as OPENCODE_CONFIG_CONTENT. No permission prompts for paths outside
# the project directory: Landlock bounds the filesystem, and the agent's instructions and
# interpreter are outside /sandbox/work by design.
#
# Input: MODEL_BASE_URL, AGENT_MODEL, AGENT_CONTEXT_LENGTH, AGENT_MCP_URL, AGENT_POLICY_SUMMARY,
# and optionally AGENT_MODEL_NAME.

set -o errexit
set -o nounset
set -o pipefail

readonly MODEL="${AGENT_MODEL:?AGENT_MODEL is not set}"
readonly URL="${MODEL_BASE_URL:?MODEL_BASE_URL is not set}"
readonly CONTEXT="${AGENT_CONTEXT_LENGTH:?AGENT_CONTEXT_LENGTH is not set}"
readonly NAME="${AGENT_MODEL_NAME:-${MODEL}}"
readonly MCP_URL="${AGENT_MCP_URL:-}"
readonly SUMMARY="${AGENT_POLICY_SUMMARY:-}"

# Only the served model is registered, so the /model picker can't select another.
models="$(jq -nc --arg model "${MODEL}" --arg name "${NAME}" --argjson context "${CONTEXT}" \
  '{($model): {name: $name, limit: {context: $context, output: 8192}}}')"

# Tools the policy denies are turned off in OpenCode too (it names them wb_<tool>), so the
# model never sees them.
mcp='{}'
tools='{}'
if [[ -n "${MCP_URL}" && -s "${SUMMARY}" ]] && jq -e '.tools.enabled == true' "${SUMMARY}" > /dev/null 2>&1; then
  mcp="$(jq -nc --arg url "${MCP_URL}" '{wb: {type: "remote", url: $url, enabled: true}}')"
  tools="$(jq -c '[(.tools.denied // [])[] | {key: ("wb_" + .), value: false}] | from_entries' "${SUMMARY}")"
fi

jq -nc --arg model "${MODEL}" --arg url "${URL}" --argjson models "${models}" \
  --argjson mcp "${mcp}" --argjson tools "${tools}" '{
  "$schema": "https://opencode.ai/config.json",
  "model": ("vllm/" + $model),
  "small_model": ("vllm/" + $model),
  "enabled_providers": ["vllm"],
  "autoupdate": false,
  "share": "disabled",
  "instructions": ["/opt/agent-sandbox/instructions.md", "/sandbox/data-access.md"],
  "permission": {"webfetch": "deny", "external_directory": "allow"},
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vLLM (local)",
      "options": {"baseURL": $url},
      "models": $models
    }
  },
  "mcp": $mcp,
  "tools": $tools
}'
