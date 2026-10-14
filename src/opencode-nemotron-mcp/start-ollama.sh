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

# A path in this file selects another model store, such as a bucket mount at
# /config/workspace/<bucket-resource>/<dir>. Its location depends on the
# workspace, so it cannot be a compose default. It takes effect when the server
# starts.
readonly MODEL_STORE_FILE="${OPENCODE_HOME:-/config}/.opencode-model-store"
if [[ -s "${MODEL_STORE_FILE}" ]]; then
  OLLAMA_MODELS="$(tr -d '[:space:]' < "${MODEL_STORE_FILE}")"
  if [[ "${OLLAMA_MODELS}" != /* || ! -d "${OLLAMA_MODELS}" ]]; then
    echo "Model store '${OLLAMA_MODELS}' in ${MODEL_STORE_FILE} is not an existing absolute directory." >&2
    echo "Check the bucket mount, or delete ${MODEL_STORE_FILE} to use the local store." >&2
    exit 1
  fi
fi

export OLLAMA_HOST="${OLLAMA_URL}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-${OPENCODE_HOME:-/config}/.ollama/models}"
export OLLAMA_NOPRUNE="${OLLAMA_NOPRUNE:-true}"
export OLLAMA_LOAD_TIMEOUT="${OLLAMA_LOAD_TIMEOUT:-20m}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
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

  # Cached weights persist in the model store. Restarts should not need registry access.
  if ! ollama show "${candidate}" > /dev/null 2>&1; then
    echo "Pulling ${candidate} (this may take several minutes)..."
    ollama pull "${candidate}" 2>&1 | tee -a "${OLLAMA_LOG}"
    PULLED=true
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
PULLED=false
for CANDIDATE in "${MODELS_TO_PREPARE[@]}"; do
  prepare_model "${CANDIDATE}"
done

# Every model is validated on first start, after a download, after an explicit
# opencode-model selection, and when the model set, store or context changes.
# Other restarts validate only the selected model: each cold load can take
# minutes, and the others have already passed with the same settings.
readonly VALIDATED_FILE="${OPENCODE_HOME:-/config}/.ollama/validated-models.json"
VALIDATED="$(jq -nc --arg store "${OLLAMA_MODELS}" --argjson context "${CONTEXT_LENGTH}" \
  '{store: $store, context_length: $context, models: ($ARGS.positional | sort)}' \
  --args "${MODELS_TO_PREPARE[@]}")"
readonly VALIDATED
VALIDATE_ALL=true
if [[ "${OPENCODE_VALIDATE_ALL:-false}" != "true" && "${PULLED}" == "false" && -s "${VALIDATED_FILE}" ]] &&
  jq -e --argjson current "${VALIDATED}" '. == $current' "${VALIDATED_FILE}" > /dev/null 2>&1; then
  VALIDATE_ALL=false
fi

# Validate sequentially, leaving the selected model resident: concurrent reads
# are slow on a bucket mount. A successful generation alone does not prove CUDA
# worked: Ollama can fall back to CPU.
# Any failure, including the selected model's, forces a full check next time.
rm -f "${VALIDATED_FILE}"
if [[ "${VALIDATE_ALL}" == "true" ]]; then
  for CANDIDATE in "${MODELS_TO_PREPARE[@]}"; do
    if [[ "${CANDIDATE}" != "${MODEL}" ]]; then
      "${SCRIPT_DIR}/validate-model.sh" "${CANDIDATE}"
    fi
  done
fi
"${SCRIPT_DIR}/validate-model.sh" "${MODEL}"
mkdir -p "$(dirname "${VALIDATED_FILE}")"
printf '%s\n' "${VALIDATED}" > "${VALIDATED_FILE}.tmp"
mv "${VALIDATED_FILE}.tmp" "${VALIDATED_FILE}"

echo "Ollama ready with ${MODEL} from ${OLLAMA_MODELS} — logs at ${OLLAMA_LOG}"
