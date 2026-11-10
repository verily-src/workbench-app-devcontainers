#!/bin/bash

# Prints the model store that start-vllm.sh must use.
#
# Usage: find-model-store.sh <model-id>...
#
# 1. The path in ~/.vllm-model-store, if set.
# 2. Otherwise a store on one of the workspace's bucket mounts (VLLM_MODEL_STORE_SEARCH, and one
#    folder below) that already holds every given model, so the app never downloads into a
#    shared bucket it didn't choose.
# 3. Otherwise the local store (VLLM_MODELS); missing models are downloaded.
#
# A store holds one folder per model, named after the Hugging Face ID with the slash replaced
# by "--", as `hf download --local-dir` writes it.

set -o errexit
set -o nounset
set -o pipefail

readonly USER_HOME_DIR="${APP_USER_HOME:-/config}"
readonly MODEL_STORE_FILE="${USER_HOME_DIR}/.vllm-model-store"
readonly SEARCH_ROOT="${VLLM_MODEL_STORE_SEARCH:-${USER_HOME_DIR}/workspace}"
readonly LOCAL_STORE="${VLLM_MODELS:-${USER_HOME_DIR}/.vllm/models}"

if [[ -s "${MODEL_STORE_FILE}" ]]; then
  STORE="$(tr -d '[:space:]' < "${MODEL_STORE_FILE}")"
  if [[ "${STORE}" != /* || ! -d "${STORE}" ]]; then
    echo "Model store '${STORE}' in ${MODEL_STORE_FILE} is not an existing absolute directory." >&2
    echo "Check the bucket mount, or delete ${MODEL_STORE_FILE} to use the local store." >&2
    exit 1
  fi
  printf '%s\n' "${STORE}"
  exit 0
fi

# Folder of a model inside a store.
model_dir() {
  printf '%s\n' "${1//\//--}"
}

holds_all() {
  local store="$1" id dir
  for id in "${@:2}"; do
    dir="${store}/$(model_dir "${id}")"
    [[ -f "${dir}/config.json" ]] || return 1
    compgen -G "${dir}/*.safetensors" > /dev/null || return 1
  done
}

if [[ "${SEARCH_ROOT}" != "off" && -d "${SEARCH_ROOT}" ]] && (( $# > 0 )); then
  shopt -s nullglob
  for candidate in "${SEARCH_ROOT}"/*/ "${SEARCH_ROOT}"/*/*/; do
    candidate="${candidate%/}"
    if holds_all "${candidate}" "$@"; then
      echo "Found every model in the bucket store ${candidate}; using it instead of downloading." >&2
      echo "To pin or change the store, write its path to ${MODEL_STORE_FILE}." >&2
      printf '%s\n' "${candidate}"
      exit 0
    fi
  done
fi

printf '%s\n' "${LOCAL_STORE}"
