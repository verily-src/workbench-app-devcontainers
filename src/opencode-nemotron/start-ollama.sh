#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

readonly OLLAMA_LOG="${OPENCODE_HOME:-/config}/ollama-server.log"
readonly OLLAMA_URL="http://127.0.0.1:11434"
SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
MODEL="${1:-$("${SCRIPT_DIR}/resolve-model.sh")}"
readonly SCRIPT_DIR MODEL
readonly CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"

if [[ ! "${CONTEXT_LENGTH}" =~ ^[1-9][0-9]*$ ]] || (( CONTEXT_LENGTH < 16384 )); then
  echo "OLLAMA_CONTEXT_LENGTH must be an integer of at least 16384 (65536 recommended)." >&2
  exit 1
fi

export OLLAMA_HOST="${OLLAMA_URL}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-${OPENCODE_HOME:-/config}/.ollama/models}"
export OLLAMA_CONTEXT_LENGTH="${CONTEXT_LENGTH}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"

server_is_up() {
  curl -fsS --connect-timeout 2 --max-time 5 "${OLLAMA_URL}/api/version" > /dev/null 2>&1
}

# postCreateCommand and postStartCommand both run on first start, so only start
# the server if it is not already listening.
if ! server_is_up; then
  nohup ollama serve >> "${OLLAMA_LOG}" 2>&1 < /dev/null &

  for _ in $(seq 30); do
    if server_is_up; then
      break
    fi
    sleep 2
  done

  if ! server_is_up; then
    echo "Ollama did not start — see ${OLLAMA_LOG}" >&2
    exit 1
  fi
fi

if [[ "${MODEL}" == "prompt" ]]; then
  echo "Ollama ready. Start opencode in a terminal to choose and download a model."
  exit 0
fi

# Cached weights persist in /config. Restarts should not need registry access.
if ! ollama show "${MODEL}" > /dev/null 2>&1; then
  echo "Pulling ${MODEL} (this may take several minutes)..."
  ollama pull "${MODEL}" 2>&1 | tee -a "${OLLAMA_LOG}"
fi

MODEL_INFO="$(curl -fsS "${OLLAMA_URL}/api/show" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg model "${MODEL}" '{model: $model}')")"
if ! jq -e '(.capabilities // []) | index("tools") != null' <<< "${MODEL_INFO}" > /dev/null; then
  echo "${MODEL} does not advertise tool support; OpenCode requires a tool-capable model." >&2
  exit 1
fi

echo "Preloading ${MODEL} into GPU memory..."
RESPONSE="$(curl -fsS "${OLLAMA_URL}/api/generate" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg model "${MODEL}" --argjson context "${CONTEXT_LENGTH}" \
    '{model: $model, prompt: "warmup", stream: false,
      options: {num_predict: 1, num_ctx: $context}}')")"
if ! jq -e '.done == true and .error == null' <<< "${RESPONSE}" > /dev/null; then
  echo "Could not load ${MODEL}: ${RESPONSE}" >&2
  exit 1
fi

echo "Ollama ready with ${MODEL} — logs at ${OLLAMA_LOG}"
