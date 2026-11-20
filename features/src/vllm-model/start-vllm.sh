#!/bin/bash

# Start vLLM serving Nemotron 3.5 Super VL, text only, across two H100s, then check it
# (README.md). Settings: VLLM_MODEL, VLLM_PORT, VLLM_BIND_ADDRESS, VLLM_MODELS,
# VLLM_CONTEXT_LENGTH, VLLM_GPU_MEMORY_UTILIZATION, VLLM_MAX_NUM_SEQS, VLLM_LOAD_TIMEOUT_MINUTES,
# VLLM_EXTRA_ARGS, VLLM_HTTP_TIMEOUT_KEEP_ALIVE.

set -o errexit
set -o nounset
set -o pipefail

readonly VENV="/opt/vllm"
readonly USER_HOME_DIR="${APP_USER_HOME:-/config}"
readonly VLLM_LOG="${USER_HOME_DIR}/vllm-server.log"
readonly STATE_DIR="${USER_HOME_DIR}/.vllm"
readonly PID_FILE="${STATE_DIR}/server.pid"
readonly PORT="${VLLM_PORT:-8000}"
readonly VLLM_URL="http://127.0.0.1:${PORT}"
readonly SUPER_VL="nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4"
readonly MODEL="${VLLM_MODEL:-${SUPER_VL}}"
# Super VL's weights at their revision on Hugging Face when this feature was written (the
# vertex-model feature's deploy-endpoint.sh pins the same one); another model at its latest.
REVISION="main"
if [[ "${MODEL}" == "${SUPER_VL}" ]]; then
  REVISION="3acb09951cff50cda7be0200ebbad2c15a3e63ba"
fi
readonly REVISION
readonly CONTEXT_LENGTH="${VLLM_CONTEXT_LENGTH:-262144}"
readonly LOAD_TIMEOUT_MINUTES="${VLLM_LOAD_TIMEOUT_MINUTES:-25}"
readonly STORE="${VLLM_MODELS:-${STATE_DIR}/models}"
readonly MODEL_DIR="${STORE}/${MODEL//\//--}"
# Written after `hf download` exits 0, holding the revision it fetched: a store without it may be
# a partial download.
readonly COMPLETE_MARKER="${MODEL_DIR}/.download-complete"

mkdir -p "${STATE_DIR}" "${STORE}"
touch "${VLLM_LOG}"

server_is_up() {
  curl -fsS --connect-timeout 2 --max-time 5 "${VLLM_URL}/health" > /dev/null 2>&1
}

served_model() {
  curl -fsS --connect-timeout 2 --max-time 10 "${VLLM_URL}/v1/models" 2> /dev/null |
    jq -r '.data[0] | "\(.id) \(.max_model_len)"' 2> /dev/null || true
}

# postCreateCommand and postStartCommand both run on first start.
if server_is_up && [[ "$(served_model)" == "${MODEL} ${CONTEXT_LENGTH}" ]]; then
  echo "vLLM already serves ${MODEL} at ${CONTEXT_LENGTH} tokens."
  exit 0
fi
if server_is_up; then
  echo "Another model is served on port ${PORT} ($(served_model)); stop it first: pkill -f '[v]llm serve'" >&2
  exit 1
fi

gpus="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2> /dev/null | awk '$1 + 0 >= 79000' | wc -l)"
if (( gpus < 2 )); then
  echo "${MODEL} needs two 80 GB GPUs (2x H100); this VM has ${gpus}." >&2
  exit 1
fi
# Tensor parallelism passes messages through /dev/shm; Docker's 64 MiB default fails at start.
shm_mib="$(df -m --output=size /dev/shm | tail -n 1 | tr -d ' ')"
if (( shm_mib < 4096 )); then
  echo "/dev/shm is ${shm_mib} MiB; this model needs a few GB (shm_size in the app's compose file)." >&2
  exit 1
fi

if [[ "$(cat "${COMPLETE_MARKER}" 2> /dev/null || true)" != "${REVISION}" ]]; then
  echo "Downloading ${MODEL} at ${REVISION} to ${MODEL_DIR} (about 75 GB)..."
  # The unauthenticated download can fail mid-way; a second run resumes it, and does nothing
  # when the files are all there.
  for attempt in 1 2 3; do
    if "${VENV}/bin/hf" download "${MODEL}" --revision "${REVISION}" --local-dir "${MODEL_DIR}" 2>&1 | tee -a "${VLLM_LOG}"; then
      printf '%s\n' "${REVISION}" > "${COMPLETE_MARKER}"
      break
    fi
    if (( attempt == 3 )); then
      echo "Could not download ${MODEL}; see ${VLLM_LOG}." >&2
      exit 1
    fi
    echo "Download interrupted; resuming (attempt $(( attempt + 1 )) of 3)..."
  done
fi

echo "Starting vLLM with ${MODEL} from ${MODEL_DIR} (log: ${VLLM_LOG})..."
readonly CUDA_DIR="/usr/local/cuda-13.0"
# VLLM_FLASHINFER_ALLREDUCE_BACKEND: "auto" picks a multi-node kernel with no prebuilt binary
# for H100, which fails to compile; trtllm ships prebuilt. Speculative decoding stays off: it
# degraded grammar-constrained tool calls in the recipe author's agent workload. Idle connections
# stay open for an hour (vLLM's default is 5 s): the sandbox's proxy does not pass the server's
# close on to the agent, whose next request would then fail once. HF_HUB_OFFLINE: the weights are
# local; vLLM must not reach Hugging Face at run time.
# shellcheck disable=SC2086 # VLLM_EXTRA_ARGS is a space-separated list by design.
env HF_HUB_OFFLINE=1 HF_HOME="${USER_HOME_DIR}/.cache/huggingface" \
  VLLM_HTTP_TIMEOUT_KEEP_ALIVE="${VLLM_HTTP_TIMEOUT_KEEP_ALIVE:-3600}" \
  CUDA_HOME="${CUDA_DIR}" PATH="${CUDA_DIR}/bin:${VENV}/bin:${PATH}" \
  LD_LIBRARY_PATH="${CUDA_DIR}/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
  VLLM_FLASHINFER_ALLREDUCE_BACKEND="${VLLM_FLASHINFER_ALLREDUCE_BACKEND:-trtllm}" \
  VLLM_CACHE_ROOT="${USER_HOME_DIR}/.cache/vllm" \
  TORCHINDUCTOR_CACHE_DIR="${USER_HOME_DIR}/.cache/torchinductor" \
  TRITON_CACHE_DIR="${USER_HOME_DIR}/.cache/triton" \
  VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 \
  nohup "${VENV}/bin/vllm" serve "${MODEL_DIR}" \
    --served-model-name "${MODEL}" \
    --trust-remote-code \
    --host "${VLLM_BIND_ADDRESS:-0.0.0.0}" --port "${PORT}" \
    --tensor-parallel-size 2 \
    --language-model-only \
    --max-model-len "${CONTEXT_LENGTH}" \
    --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.89}" \
    --max-num-seqs "${VLLM_MAX_NUM_SEQS:-8}" \
    --max-num-batched-tokens 16384 \
    --block-size 64 \
    --enable-prefix-caching \
    --prefix-match-unit 64 \
    --mamba-backend flashinfer \
    --mamba-cache-mode align \
    --mamba-ssm-cache-dtype float16 \
    --enable-mamba-cache-stochastic-rounding \
    --mamba-cache-philox-rounds 5 \
    --enable-mamba-shared-prefix-checkpoint \
    --async-scheduling \
    --reasoning-parser nemotron_v3 \
    --reasoning-config '{"reasoning_end_str": "\n\nEnough thinking, time to act.\n\n</think>"}' \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --tool-strict-level parameter \
    --enable-prompt-tokens-details \
    --structured-outputs-config '{"backend": "xgrammar", "disable_any_whitespace": true}' \
    ${VLLM_EXTRA_ARGS:-} \
    >> "${VLLM_LOG}" 2>&1 < /dev/null &
SERVER_PID=$!
printf '%s\n' "${SERVER_PID}" > "${PID_FILE}"

DEADLINE=$(( SECONDS + LOAD_TIMEOUT_MINUTES * 60 ))
until server_is_up; do
  if ! kill -0 "${SERVER_PID}" 2> /dev/null; then
    echo "vLLM exited during startup (${VLLM_LOG}). Error lines:" >&2
    grep -nE '([A-Za-z]+Error|Exception)(:| )|CUDA error|out of memory|not supported|No such file|/dev/shm' "${VLLM_LOG}" |
      grep -vE 'core\.py:[0-9]+\] +(File |\^|Traceback)' | tail -n 15 >&2
    echo "Last log lines:" >&2
    tail -n 40 "${VLLM_LOG}" >&2
    exit 1
  fi
  if (( SECONDS >= DEADLINE )); then
    echo "vLLM did not become ready within ${LOAD_TIMEOUT_MINUTES} minutes; see ${VLLM_LOG}" >&2
    exit 1
  fi
  sleep 5
done
echo "vLLM is up after ${SECONDS} s."

if [[ "$(served_model)" != "${MODEL} ${CONTEXT_LENGTH}" ]]; then
  echo "vLLM is not serving ${MODEL} at ${CONTEXT_LENGTH} tokens: $(served_model)" >&2
  exit 1
fi
# One short generation; the first request can also compile CUDA graphs.
if ! curl -fsS --connect-timeout 5 --max-time 600 "${VLLM_URL}/v1/chat/completions" -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg model "${MODEL}" '{model: $model, max_tokens: 8, temperature: 0, messages: [{role: "user", content: "Reply with one word: ready"}]}')" |
    jq -e '(.usage.completion_tokens // 0) >= 1' > /dev/null; then
  echo "${MODEL} did not answer a chat request; see ${VLLM_LOG}." >&2
  exit 1
fi
printf '%s\n' "${MODEL}" > "${STATE_DIR}/server.model"
echo "vLLM ready with ${MODEL} at ${CONTEXT_LENGTH} tokens; logs at ${VLLM_LOG}"
