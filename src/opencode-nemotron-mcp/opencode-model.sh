#!/bin/bash

# Select, download, validate, and persist one local model. Safe to rerun.
set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
readonly USER_HOME_DIR="${OPENCODE_HOME:-/config}"
readonly CATALOG="${SCRIPT_DIR}/models.json"

usage() {
  echo "Usage: opencode-model [--list | <ollama-model-tag>]"
  echo "With no arguments, choose a model interactively. Only that model is downloaded."
}

list_models() {
  jq -r 'to_entries[] | "\(.key + 1). \(.value.tag) — \(.value.weights) weights; \(.value.gpu)"' "${CATALOG}"
}

if (( $# > 1 )); then
  usage >&2
  exit 1
fi

case "${1:-}" in
  --list) list_models; exit 0 ;;
  --help|-h) usage; exit 0 ;;
esac

MODEL="${1:-}"
if [[ -z "${MODEL}" ]]; then
  if [[ ! -t 0 || ! -t 1 ]]; then
    echo "Model selection needs a terminal. Run opencode-model <ollama-model-tag>." >&2
    exit 1
  fi
  echo "Choose a local Nemotron model (GPU guidance is an estimate; check ollama ps)."
  if command -v nvidia-smi > /dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
  fi
  list_models
  read -r -p "Model [1, or q to cancel]: " CHOICE || exit 1
  CHOICE="${CHOICE:-1}"
  if [[ "${CHOICE}" == "q" || "${CHOICE}" == "Q" ]]; then
    exit 1
  fi
  if [[ ! "${CHOICE}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Select a number from the list." >&2
    exit 1
  fi
  MODEL="$(jq -r --argjson choice "${CHOICE}" '.[$choice - 1].tag // empty' "${CATALOG}")"
fi

if [[ "${MODEL}" == "prompt" || ! "${MODEL}" =~ ^[[:alnum:]][[:alnum:]_.:/-]*$ ]]; then
  echo "Invalid model tag or selection: ${MODEL}" >&2
  exit 1
fi

# Do not change the saved selection/configuration if download or loading fails.
"${SCRIPT_DIR}/start-ollama.sh" "${MODEL}"
"${SCRIPT_DIR}/configure-opencode.sh" "$(id -un)" "${USER_HOME_DIR}" "${MODEL}"
printf '%s\n' "${MODEL}" > "${USER_HOME_DIR}/.opencode-model.tmp"
mv "${USER_HOME_DIR}/.opencode-model.tmp" "${USER_HOME_DIR}/.opencode-model"
echo "Selected ${MODEL}. Start a new OpenCode session to use it."
