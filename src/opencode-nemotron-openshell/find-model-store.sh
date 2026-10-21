#!/bin/bash

# Prints the Ollama model store that start-ollama.sh must use.
#
# Usage: find-model-store.sh <model-tag>...
#
# 1. A path in /config/.opencode-model-store, if set, always wins.
# 2. Otherwise, the workspace's bucket mounts (/config/workspace/<bucket>, and
#    one folder level below) are searched for an Ollama store that already holds
#    every given model. The first match, in name order, is used. Set
#    OPENCODE_MODEL_STORE_SEARCH=off to skip the search, or to another
#    directory to search there instead.
# 3. Otherwise, the local store (OLLAMA_MODELS, default /config/.ollama/models).
#    Missing models are then downloaded from Ollama's registry.
#
# A store is used only if it holds every model, so the app never writes new
# downloads into a shared bucket it didn't choose explicitly.

set -o errexit
set -o nounset
set -o pipefail

readonly USER_HOME_DIR="${OPENCODE_HOME:-/config}"
readonly MODEL_STORE_FILE="${USER_HOME_DIR}/.opencode-model-store"
readonly SEARCH_ROOT="${OPENCODE_MODEL_STORE_SEARCH:-${USER_HOME_DIR}/workspace}"
readonly LOCAL_STORE="${OLLAMA_MODELS:-${USER_HOME_DIR}/.ollama/models}"

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

# Manifest path of a tag in an Ollama store: name:tag, namespace/name:tag, or
# host/namespace/name:tag. A missing tag means "latest".
manifest_path() {
  local reference="$1" name tag
  name="${reference%%:*}"
  tag="latest"
  if [[ "${reference}" == *:* ]]; then
    tag="${reference#*:}"
  fi
  case "${name}" in
    */*/*) printf 'manifests/%s/%s\n' "${name}" "${tag}" ;;
    */*) printf 'manifests/registry.ollama.ai/%s/%s\n' "${name}" "${tag}" ;;
    *) printf 'manifests/registry.ollama.ai/library/%s/%s\n' "${name}" "${tag}" ;;
  esac
}

holds_all() {
  local store="$1" tag
  [[ -d "${store}/blobs" && -d "${store}/manifests" ]] || return 1
  for tag in "${@:2}"; do
    [[ -f "${store}/$(manifest_path "${tag}")" ]] || return 1
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
