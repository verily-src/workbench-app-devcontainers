#!/bin/bash

# Check that the running vLLM serves exactly the given model, on the GPU, at the
# configured context length, and answers a chat request.
set -o errexit
set -o nounset
set -o pipefail

readonly MODEL="${1:?Usage: validate-model.sh <model-id>}"
readonly CONTEXT_LENGTH="${VLLM_CONTEXT_LENGTH:-65536}"
readonly VLLM_URL="http://127.0.0.1:${VLLM_PORT:-8000}"
readonly GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
if [[ ! "${CONTEXT_LENGTH}" =~ ^[1-9][0-9]*$ ]] || (( CONTEXT_LENGTH < 16384 )); then
  echo "VLLM_CONTEXT_LENGTH must be an integer of at least 16384." >&2
  exit 1
fi

echo "Checking ${MODEL} at ${CONTEXT_LENGTH} tokens..."
if ! MODELS="$(curl -fsS --connect-timeout 5 --max-time 30 "${VLLM_URL}/v1/models")"; then
  echo "vLLM is not answering at ${VLLM_URL}. Check ~/vllm-server.log." >&2
  exit 1
fi
if ! jq -e --arg model "${MODEL}" --argjson context "${CONTEXT_LENGTH}" '
  (.data | length) == 1 and .data[0].id == $model and .data[0].max_model_len == $context
' <<< "${MODELS}" > /dev/null; then
  echo "vLLM is not serving ${MODEL} alone at ${CONTEXT_LENGTH} tokens. Actual: ${MODELS}" >&2
  exit 1
fi

# The weights and the KV/state cache are allocated on the GPU before the server
# answers; vLLM has no CPU fallback. Require the reserved fraction, with margin.
if ! command -v nvidia-smi > /dev/null 2>&1; then
  echo "nvidia-smi is unavailable; cannot confirm the GPU." >&2
  exit 1
fi
read -r USED_MIB TOTAL_MIB < <(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits |
  awk -F', *' 'NR == 1 { print $1, $2 }')
MIN_MIB="$(awk -v total="${TOTAL_MIB}" -v util="${GPU_MEMORY_UTILIZATION}" 'BEGIN { printf "%d", total * util * 0.8 }')"
if (( USED_MIB < MIN_MIB )); then
  echo "${MODEL} failed GPU preflight: ${USED_MIB} MiB in use, expected at least ${MIN_MIB} MiB (${GPU_MEMORY_UTILIZATION} of ${TOTAL_MIB} MiB reserved)." >&2
  echo "Check nvidia-smi, the CUDA driver (580+ for this vLLM release), and ~/vllm-server.log." >&2
  exit 1
fi

# One short generation. The first request after a start can also compile
# CUDA graphs for new shapes, so allow a few minutes.
if ! RESPONSE="$(curl -fsS --connect-timeout 5 --max-time 600 "${VLLM_URL}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg model "${MODEL}" \
    '{model: $model, max_tokens: 8, temperature: 0, messages: [{role: "user", content: "Reply with one word: ready"}]}')")"; then
  echo "Could not generate with ${MODEL}. Check ~/vllm-server.log and nvidia-smi; retry vllm-model after correcting the failure." >&2
  exit 1
fi
if ! jq -e '(.choices | length) == 1 and (.usage.completion_tokens // 0) >= 1' <<< "${RESPONSE}" > /dev/null; then
  echo "Unexpected response from ${MODEL}: ${RESPONSE}" >&2
  exit 1
fi
echo "Verified ${MODEL}: served on the GPU (${USED_MIB} of ${TOTAL_MIB} MiB in use), ${CONTEXT_LENGTH}-token context."
