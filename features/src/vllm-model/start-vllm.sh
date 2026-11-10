#!/bin/bash

# Start (or restart) vLLM serving the selected model, then check it. vLLM serves
# one model per process, so a model change restarts the server.

set -o errexit
set -o nounset
set -o pipefail

readonly USER_HOME_DIR="${APP_USER_HOME:-/config}"
readonly VLLM_LOG="${USER_HOME_DIR}/vllm-server.log"
readonly STATE_DIR="${USER_HOME_DIR}/.vllm"
readonly PID_FILE="${STATE_DIR}/server.pid"
readonly PORT="${VLLM_PORT:-8000}"
readonly VLLM_URL="http://127.0.0.1:${PORT}"
readonly VLLM_BIN="${VLLM_BIN:-/opt/vllm/bin/vllm}"
readonly HF_BIN="${HF_BIN:-/opt/vllm/bin/hf}"
SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
MODEL="${1:-$("${SCRIPT_DIR}/resolve-model.sh")}"
readonly SCRIPT_DIR MODEL
readonly CONTEXT_LENGTH="${VLLM_CONTEXT_LENGTH:-65536}"
readonly LOAD_TIMEOUT_MINUTES="${VLLM_LOAD_TIMEOUT_MINUTES:-25}"
AVAILABLE_MODELS="$("${SCRIPT_DIR}/available-models.sh")"
readonly AVAILABLE_MODELS
EXPECTED_VERSION="$(jq -r .version "${SCRIPT_DIR}/vllm-release.json")"
readonly EXPECTED_VERSION

if [[ ! "${CONTEXT_LENGTH}" =~ ^[1-9][0-9]*$ ]] || (( CONTEXT_LENGTH < 16384 )); then
  echo "VLLM_CONTEXT_LENGTH must be an integer of at least 16384 (65536 recommended)." >&2
  exit 1
fi
if [[ ! "${LOAD_TIMEOUT_MINUTES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "VLLM_LOAD_TIMEOUT_MINUTES must be a positive integer." >&2
  exit 1
fi
mkdir -p "${STATE_DIR}"
touch "${VLLM_LOG}"

server_is_up() {
  curl -fsS --connect-timeout 2 --max-time 5 "${VLLM_URL}/health" > /dev/null 2>&1
}

server_version() {
  curl -fsS --connect-timeout 2 --max-time 10 "${VLLM_URL}/version" 2> /dev/null | jq -r '.version // empty'
}

# "<model id> <max_model_len>" of the served model, if the server answers.
served_model() {
  curl -fsS --connect-timeout 2 --max-time 10 "${VLLM_URL}/v1/models" 2> /dev/null |
    jq -r '.data[0] | "\(.id) \(.max_model_len)"' 2> /dev/null || true
}

stop_server() {
  local pid=""
  if [[ -s "${PID_FILE}" ]]; then
    pid="$(cat "${PID_FILE}")"
  fi
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2> /dev/null; then
    echo "Stopping vLLM (pid ${pid})..."
    kill "${pid}" 2> /dev/null || true
  else
    # A server left by an earlier version without a pid file.
    pkill -u "$(id -u)" -f "${VLLM_BIN} serve" 2> /dev/null || true
  fi
  for _ in $(seq 60); do
    if ! server_is_up && { [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2> /dev/null; }; then
      rm -f "${PID_FILE}"
      return 0
    fi
    sleep 2
  done
  echo "vLLM did not stop within two minutes; see ${VLLM_LOG}." >&2
  exit 1
}

IN_CATALOG="$(jq -r --arg model "${MODEL}" 'any(.id == $model)' "${SCRIPT_DIR}/models.json")"
IS_AVAILABLE="$(jq -r --arg model "${MODEL}" 'any(.id == $model)' <<< "${AVAILABLE_MODELS}")"
if [[ "${IN_CATALOG}" == "true" && "${IS_AVAILABLE}" != "true" ]]; then
  echo "${MODEL} is not available on this GPU (models.json names each model's minimum VRAM)." >&2
  exit 1
fi

# The model store (find-model-store.sh).
STORE="$(APP_USER_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/find-model-store.sh" "${MODEL}")"
MODEL_DIR="${STORE}/${MODEL//\//--}"
REVISION="$(jq -r --arg model "${MODEL}" '.[] | select(.id == $model) | .revision // empty' "${SCRIPT_DIR}/models.json")"

# Cached weights persist in the model store. Restarts should not need Hugging Face.
if [[ ! -f "${MODEL_DIR}/config.json" ]] || ! compgen -G "${MODEL_DIR}/*.safetensors" > /dev/null; then
  echo "Downloading ${MODEL}${REVISION:+ at ${REVISION}} to ${MODEL_DIR} (this may take several minutes)..."
  "${HF_BIN}" download "${MODEL}" ${REVISION:+--revision "${REVISION}"} --local-dir "${MODEL_DIR}" 2>&1 | tee -a "${VLLM_LOG}"
  if [[ -n "${REVISION}" ]]; then
    printf '%s\n' "${REVISION}" > "${MODEL_DIR}/.revision"
  fi
fi
if [[ -n "${REVISION}" && -s "${MODEL_DIR}/.revision" && "$(tr -d '[:space:]' < "${MODEL_DIR}/.revision")" != "${REVISION}" ]]; then
  echo "Warning: ${MODEL_DIR} holds revision $(cat "${MODEL_DIR}/.revision"), the catalog pins ${REVISION}." >&2
fi

# A store on a bucket mount is prefetched into the page cache with sequential reads, which
# gcsfuse serves about ten times faster than the loader's own page faults.
BUCKET_URL="$("${SCRIPT_DIR}/model-source.sh" "${MODEL_DIR}")"

prefetch_store() {
  local started size
  started=${SECONDS}
  size="$(du -sh "${MODEL_DIR}" 2> /dev/null | cut -f1)"
  echo "Prefetching ${MODEL_DIR} (${size:-?}) from the bucket mount into the page cache..."
  # One file at a time: gcsfuse reads fast sequentially and badly when readers interleave.
  for shard in "${MODEL_DIR}"/*.safetensors; do
    cat "${shard}" > /dev/null
  done
  echo "Prefetched in $(( SECONDS - started )) s."
}

# Per-model serve arguments from the catalog (quantization and kernel backends).
MODEL_ARGS=()
while IFS= read -r ARG; do
  MODEL_ARGS+=("${ARG}")
done < <(jq -r --arg model "${MODEL}" '.[] | select(.id == $model) | .serve_args[]?' "${SCRIPT_DIR}/models.json")

# postCreateCommand and postStartCommand both run on first start, so reuse a
# server that already serves the selected model at the configured context.
if server_is_up; then
  SERVER_VERSION="$(server_version)"
  if [[ "${SERVER_VERSION}" != "${EXPECTED_VERSION}" ]]; then
    echo "vLLM ${EXPECTED_VERSION} is required; server is ${SERVER_VERSION:-unknown}. Rebuild/restart the container." >&2
    exit 1
  fi
  if [[ "$(served_model)" == "${MODEL} ${CONTEXT_LENGTH}" ]]; then
    echo "vLLM already serves ${MODEL} at ${CONTEXT_LENGTH} tokens."
  else
    stop_server
  fi
fi

if ! server_is_up; then
  if [[ -n "${BUCKET_URL}" ]]; then
    prefetch_store
  fi
  echo "Starting vLLM with ${MODEL} from ${MODEL_DIR} (log: ${VLLM_LOG})..."
  # HF_HUB_OFFLINE: the weights are local; vLLM must not reach Hugging Face at run time.
  # The compile caches are kept under the user's home, which persists; their defaults are in /tmp.
  # The Humming kernels JIT-compile with NVRTC, which must find the CUDA libraries pip installed
  # with vLLM (CUDA_DIR); there is no system CUDA in this image.
  CUDA_DIR="$(dirname "$(dirname "$(compgen -G "$(dirname "$(dirname "${VLLM_BIN}")")/lib/python3*/site-packages/nvidia/cu13/lib/libnvrtc-builtins.so*" | head -n 1 || true)" 2> /dev/null || true)" 2> /dev/null || true)"
  CUDA_LIB_DIR="${CUDA_DIR:+${CUDA_DIR}/lib}"
  # Idle connections stay open for an hour (vLLM's default is 5 s): the sandbox's proxy does not
  # pass the server's close on to the agent, whose next request would then fail once.
  # shellcheck disable=SC2086 # VLLM_EXTRA_ARGS is a space-separated list by design.
  env HF_HUB_OFFLINE=1 HF_HOME="${USER_HOME_DIR}/.cache/huggingface" \
    VLLM_HTTP_TIMEOUT_KEEP_ALIVE="${VLLM_HTTP_TIMEOUT_KEEP_ALIVE:-3600}" \
    CUDA_HOME="${CUDA_DIR:-/usr/local/cuda}" PATH="${CUDA_DIR:+${CUDA_DIR}/bin:}${PATH}" \
    LD_LIBRARY_PATH="${CUDA_LIB_DIR:+${CUDA_LIB_DIR}:}${LD_LIBRARY_PATH:-}" \
    VLLM_USE_V2_MODEL_RUNNER=1 \
    VLLM_CACHE_ROOT="${USER_HOME_DIR}/.cache/vllm" \
    TORCHINDUCTOR_CACHE_DIR="${USER_HOME_DIR}/.cache/torchinductor" \
    TRITON_CACHE_DIR="${USER_HOME_DIR}/.cache/triton" \
    VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 VLLM_HUMMING_MOE_GEMM_TYPE=indexed \
    nohup "${VLLM_BIN}" serve "${MODEL_DIR}" \
      --served-model-name "${MODEL}" \
      --host "${VLLM_BIND_ADDRESS:-0.0.0.0}" --port "${PORT}" \
      --max-model-len "${CONTEXT_LENGTH}" \
      --max-num-seqs "${VLLM_MAX_NUM_SEQS:-8}" \
      --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.90}" \
      --mamba-cache-mode align \
      --enable-prefix-caching --async-scheduling \
      --reasoning-parser nemotron_v3 \
      --tool-call-parser qwen3_coder --enable-auto-tool-choice \
      --tool-strict-level parameter \
      --structured-outputs-config '{"backend": "xgrammar", "disable_any_whitespace": true}' \
      --enable-prompt-tokens-details \
      ${MODEL_ARGS[@]+"${MODEL_ARGS[@]}"} ${VLLM_EXTRA_ARGS:-} \
      >> "${VLLM_LOG}" 2>&1 < /dev/null &
  SERVER_PID=$!
  printf '%s\n' "${SERVER_PID}" > "${PID_FILE}"

  DEADLINE=$(( SECONDS + LOAD_TIMEOUT_MINUTES * 60 ))
  until server_is_up; do
    if ! kill -0 "${SERVER_PID}" 2> /dev/null; then
      echo "vLLM exited during startup (${VLLM_LOG})." >&2
      # The engine runs in a child process whose error surfaces well before the
      # API server's own traceback, so a tail of the log misses the cause.
      echo "Error lines:" >&2
      grep -nE '([A-Za-z]+Error|Exception)(:| )|CUDA error|out of memory|not supported|No such file' "${VLLM_LOG}" \
        | grep -vE 'core\.py:[0-9]+\] +(File |\^|Traceback)' | tail -n 15 >&2
      echo "Last log lines:" >&2
      tail -n 40 "${VLLM_LOG}" >&2
      exit 1
    fi
    if (( SECONDS >= DEADLINE )); then
      echo "vLLM did not become ready within ${LOAD_TIMEOUT_MINUTES} minutes — see ${VLLM_LOG}" >&2
      exit 1
    fi
    sleep 5
  done
  echo "vLLM is up after ${SECONDS} s."

  SERVER_VERSION="$(server_version)"
  if [[ "${SERVER_VERSION}" != "${EXPECTED_VERSION}" ]]; then
    echo "vLLM ${EXPECTED_VERSION} is required; server is ${SERVER_VERSION:-unknown}. Rebuild/restart the container." >&2
    exit 1
  fi
fi

# A successful answer alone does not prove the GPU is used; validate-model.sh
# also checks the GPU memory reservation and the served context length.
VLLM_PORT="${PORT}" VLLM_CONTEXT_LENGTH="${CONTEXT_LENGTH}" "${SCRIPT_DIR}/validate-model.sh" "${MODEL}"
printf '%s\n' "${MODEL}" > "${STATE_DIR}/server.model"

echo "vLLM ready with ${MODEL} from ${MODEL_DIR} — logs at ${VLLM_LOG}"
