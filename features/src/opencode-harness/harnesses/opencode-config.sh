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

# This runs on the broker, where HOME is the app user's writable home and jq loads ~/.jq: a file
# there could redefine builtins the programs below use.
jq() { HOME=/nonexistent command jq "$@"; }

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
# OpenCode's own tools that do nothing here or only add steps, off so their definitions are not
# sent on every step: webfetch and websearch (no internet), task (subagents: each a session of its
# own, the steps and the cost of another agent) and todowrite (a planning step between steps).
readonly BUILTIN_OFF='{"webfetch": false, "websearch": false, "task": false, "todowrite": false}'

mcp='{}'
tools="${BUILTIN_OFF}"
wb_ask='{}'
if [[ -n "${MCP_URL}" && -s "${SUMMARY}" ]] && jq -e '.tools.enabled == true' "${SUMMARY}" > /dev/null 2>&1; then
  mcp="$(jq -nc --arg url "${MCP_URL}" '{wb: {type: "remote", url: $url, enabled: true}}')"
  tools="$(jq -c --argjson off "${BUILTIN_OFF}" '$off + ([(.tools.denied // [])[] | {key: ("wb_" + .), value: false}] | from_entries)' "${SUMMARY}")"
  wb_ask="$(jq -c '[(.tools.ask // [])[] | {key: ("wb_" + .), value: "ask"}] | from_entries' "${SUMMARY}")"
fi

# The Workbench tools the summary's tools.ask names get the same prompt. The other MCP servers
# the policy opened (the summary's servers): each registered under its
# name, with the tools the policy denies turned off and the ones its catalog marks `ask` behind
# OpenCode's permission prompt, so the person answers before the call is made.
permission="$(jq -nc --argjson ask "${wb_ask}" '{"webfetch": "deny", "external_directory": "allow"} + $ask')"
if [[ -s "${SUMMARY}" ]]; then
  mcp="$(jq -c --argjson mcp "${mcp}" \
    '$mcp + ([(.servers // [])[] | {key: .name, value: {type: "remote", url: .url, enabled: true}}] | from_entries)' "${SUMMARY}")"
  tools="$(jq -c --argjson tools "${tools}" \
    '$tools + ([(.servers // [])[] | .name as $n | .denied[] | {key: ($n + "_" + .), value: false}] | from_entries)' "${SUMMARY}")"
  permission="$(jq -c --argjson permission "${permission}" \
    '$permission + ([(.servers // [])[] | .name as $n | .ask[] | {key: ($n + "_" + .), value: "ask"}] | from_entries)' "${SUMMARY}")"
fi

jq -nc --arg model "${MODEL}" --arg url "${URL}" --argjson models "${models}" \
  --argjson mcp "${mcp}" --argjson tools "${tools}" --argjson permission "${permission}" '{
  "$schema": "https://opencode.ai/config.json",
  "model": ("vllm/" + $model),
  "small_model": ("vllm/" + $model),
  "enabled_providers": ["vllm"],
  "autoupdate": false,
  "share": "disabled",
  "instructions": ["/opt/agent-sandbox/instructions.md", "/sandbox/data-access.md"],
  "permission": $permission,
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
