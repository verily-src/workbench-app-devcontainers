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
AVAILABLE_MODELS="$("${SCRIPT_DIR}/available-models.sh")"
readonly AVAILABLE_MODELS

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

EXPECTED_VERSION="$(jq -r .version "${SCRIPT_DIR}/ollama-release.json")"
SERVER_VERSION="$(curl -fsS --connect-timeout 2 --max-time 10 "${OLLAMA_URL}/api/version" | jq -r .version)"
if [[ "${SERVER_VERSION}" != "${EXPECTED_VERSION}" ]]; then
  echo "Ollama ${EXPECTED_VERSION} is required; server is ${SERVER_VERSION}. Rebuild/restart the container." >&2
  exit 1
fi

if [[ "${MODEL}" == "prompt" ]]; then
  echo "Ollama ready. Start opencode in a terminal to choose and download a model."
  exit 0
fi

IN_CATALOG="$(jq -r --arg model "${MODEL}" 'any(.tag == $model)' "${SCRIPT_DIR}/models.json")"
IS_AVAILABLE="$(jq -r --arg model "${MODEL}" 'any(.tag == $model)' <<< "${AVAILABLE_MODELS}")"
if [[ "${IN_CATALOG}" == "true" && "${IS_AVAILABLE}" != "true" ]]; then
  echo "${MODEL} is not available on this GPU. Run opencode-model --list for compatible models." >&2
  exit 1
fi

prepare_model() {
  local candidate="$1"

  # Cached weights persist in /config. Restarts should not need registry access.
  if ! ollama show "${candidate}" > /dev/null 2>&1; then
    echo "Pulling ${candidate} (this may take several minutes)..."
    ollama pull "${candidate}" 2>&1 | tee -a "${OLLAMA_LOG}"
  fi

  local model_info
  model_info="$(curl -fsS --connect-timeout 2 --max-time 30 "${OLLAMA_URL}/api/show" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg model "${candidate}" '{model: $model}')")"
  if ! jq -e '(.capabilities // []) | index("tools") != null' <<< "${model_info}" > /dev/null; then
    echo "${candidate} does not advertise tool support; OpenCode requires a tool-capable model." >&2
    exit 1
  fi
}

# Pull every compatible catalog model so each entry exposed by OpenCode's
# /model picker is immediately usable. A custom selected tag is prepared too.
MODELS_TO_PREPARE=()
while IFS= read -r CANDIDATE; do
  MODELS_TO_PREPARE+=("${CANDIDATE}")
done < <(jq -r '.[].tag' <<< "${AVAILABLE_MODELS}")
if [[ "${IS_AVAILABLE}" != "true" ]]; then
  MODELS_TO_PREPARE+=("${MODEL}")
fi
for CANDIDATE in "${MODELS_TO_PREPARE[@]}"; do
  prepare_model "${CANDIDATE}"
done

# Validate sequentially, leaving the selected model resident. A successful
# generation alone does not prove CUDA worked: Ollama can fall back to CPU.
for CANDIDATE in "${MODELS_TO_PREPARE[@]}"; do
  if [[ "${CANDIDATE}" != "${MODEL}" ]]; then
    "${SCRIPT_DIR}/validate-model.sh" "${CANDIDATE}"
  fi
done
"${SCRIPT_DIR}/validate-model.sh" "${MODEL}"

echo "Ollama ready with ${MODEL} — logs at ${OLLAMA_LOG}"
