#!/bin/bash

# Load one model and verify the same full-GPU condition shown by ollama ps.
set -o errexit
set -o nounset
set -o pipefail

readonly MODEL="${1:?Usage: validate-model.sh <model>}"
readonly CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
readonly OLLAMA_URL="http://127.0.0.1:11434"
if [[ ! "${CONTEXT_LENGTH}" =~ ^[1-9][0-9]*$ ]] || (( CONTEXT_LENGTH < 16384 )); then
  echo "OLLAMA_CONTEXT_LENGTH must be an integer of at least 16384." >&2
  exit 1
fi

echo "Checking ${MODEL} at ${CONTEXT_LENGTH} tokens (load timeout: 10 minutes)..."
if ! RESPONSE="$(curl -fsS --connect-timeout 5 --max-time 600 "${OLLAMA_URL}/api/generate" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg model "${MODEL}" --argjson context "${CONTEXT_LENGTH}" \
    '{model: $model, prompt: "warmup", stream: false, keep_alive: "5m",
      options: {num_predict: 1, num_ctx: $context}}')")"; then
  echo "Could not load ${MODEL}. Check ~/ollama-server.log and nvidia-smi; retry opencode-model after correcting the failure." >&2
  exit 1
fi
if ! jq -e '.done == true and .error == null' <<< "${RESPONSE}" > /dev/null; then
  echo "Could not load ${MODEL}: ${RESPONSE}" >&2
  exit 1
fi

STATUS="$(curl -fsS --connect-timeout 5 --max-time 15 "${OLLAMA_URL}/api/ps")"
if ! jq -e --arg model "${MODEL}" --argjson context "${CONTEXT_LENGTH}" '
  (.models | length) == 1 and
  any(.models[]; (.name == $model or .model == $model) and
    .size > 0 and .size_vram == .size and .context_length == $context)
' <<< "${STATUS}" > /dev/null; then
  echo "${MODEL} failed GPU preflight: expected one fully GPU-resident model at ${CONTEXT_LENGTH} tokens." >&2
  echo "Check nvidia-smi, CUDA driver support, free VRAM, and OLLAMA_MAX_LOADED_MODELS=1. Actual Ollama status: ${STATUS}" >&2
  exit 1
fi
echo "Verified ${MODEL}: 100% GPU, ${CONTEXT_LENGTH}-token context."
