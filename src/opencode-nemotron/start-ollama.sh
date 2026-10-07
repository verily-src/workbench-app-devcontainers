#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

readonly OLLAMA_LOG="/config/ollama-server.log"
readonly OLLAMA_URL="http://localhost:11434"
readonly NANO_9B_SOURCE="hf.co/bartowski/nvidia_NVIDIA-Nemotron-Nano-9B-v2-GGUF:Q4_K_M"
readonly NANO_9B_MODEL="nemotron-nano-9b:v2"
readonly SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly NANO_9B_TEMPLATE="${SCRIPT_DIR}/Modelfile-nano-9b-v2"

server_is_up() {
  curl -fsS "${OLLAMA_URL}/api/version" > /dev/null 2>&1
}

wait_for_server() {
  local check="$1"
  for _ in $(seq 30); do
    if "${check}"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# postCreateCommand and postStartCommand both run on first start, so check
# whether the server and models are already present.
if ! server_is_up; then
  nohup ollama serve > "${OLLAMA_LOG}" 2>&1 &
  if ! wait_for_server server_is_up; then
    echo "Ollama did not start — see ${OLLAMA_LOG}" >&2
    exit 1
  fi
fi

ensure_model() {
  local model="$1"
  if ! ollama show "${model}" > /dev/null 2>&1; then
    echo "Pulling ${model} (this may take several minutes)..."
    ollama pull "${model}" >> "${OLLAMA_LOG}" 2>&1
  fi
}

existing_modelfile="$(ollama show --modelfile "${NANO_9B_MODEL}" 2>/dev/null || true)"
if [[ "${existing_modelfile}" != *'TEMPLATE """<SPECIAL_10>System'* ]]; then
  if ollama show "${NANO_9B_MODEL}" > /dev/null 2>&1; then
    # Repair an existing alias created with Ollama's incompatible ChatML
    # nemotron-3-nano renderer without downloading the GGUF again.
    gguf_model="${NANO_9B_MODEL}"
  else
    ensure_model "${NANO_9B_SOURCE}"
    gguf_model="${NANO_9B_SOURCE}"
  fi

  gguf_modelfile="$(ollama show --modelfile "${gguf_model}")"
  gguf_blob="$(awk '$1 == "FROM" && $2 ~ /^\// { print $2; exit }' <<< "${gguf_modelfile}")"
  if [[ -z "${gguf_blob}" || ! -f "${gguf_blob}" ]]; then
    echo "Cannot find the local Nano 9B GGUF blob for ${gguf_model}" >&2
    exit 1
  fi

  modelfile="$(mktemp)"
  sed "s|__GGUF_BLOB__|${gguf_blob}|" "${NANO_9B_TEMPLATE}" > "${modelfile}"
  echo "Configuring ${NANO_9B_MODEL} with the Nano 9B v2 chat template..."
  ollama create "${NANO_9B_MODEL}" -f "${modelfile}" >> "${OLLAMA_LOG}" 2>&1
  rm -f "${modelfile}"
fi

configured_modelfile="$(ollama show --modelfile "${NANO_9B_MODEL}")"
if [[ "${configured_modelfile}" != *'TEMPLATE """<SPECIAL_10>System'* ]]; then
  echo "Nano 9B v2 chat template was not installed" >&2
  exit 1
fi
if [[ "${configured_modelfile}" == *$'\nRENDERER nemotron-3-nano\n'* ]]; then
  echo "Nano 9B v2 still uses Ollama's incompatible nemotron-3-nano renderer" >&2
  exit 1
fi

# The alias keeps the same GGUF blob. Remove the long source tag so Ollama
# and OpenCode each list just the three supported models, including after a
# restart that interrupted the earlier cleanup.
if ollama show "${NANO_9B_SOURCE}" > /dev/null 2>&1; then
  ollama rm "${NANO_9B_SOURCE}" >> "${OLLAMA_LOG}" 2>&1
fi

ensure_model "nemotron-3-nano:4b"
ensure_model "nemotron-3.5-lightning:30b"

echo "Ollama ready with 4B, 9B v2, and Lightning 30B — logs at ${OLLAMA_LOG}"
