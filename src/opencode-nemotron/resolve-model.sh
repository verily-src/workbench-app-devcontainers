#!/bin/bash

# Prints the Ollama model tag that the app must use.
#
# Workbench substitutes only a fixed set of template options on the VM, so the
# tag cannot be a template option. An operator overrides the docker-compose
# default by writing a tag to /config/.opencode-model. /config is a volume, so
# the override survives a restart and a machine-type change. Example: a move
# from an A100 to an L4 needs a model that fits in less VRAM.

set -o errexit
set -o nounset
set -o pipefail

readonly MODEL_OVERRIDE_FILE="${OPENCODE_HOME:-/config}/.opencode-model"
readonly DEFAULT_MODEL="nemotron-3-nano:4b"

if [[ -s "${MODEL_OVERRIDE_FILE}" ]]; then
  MODEL="$(tr -d '[:space:]' < "${MODEL_OVERRIDE_FILE}")"
else
  MODEL="${OLLAMA_MODEL:-${DEFAULT_MODEL}}"
fi

# "prompt" is a startup policy, never an Ollama model to download.
if [[ ! "${MODEL}" =~ ^[[:alnum:]][[:alnum:]_.:/-]*$ ]]; then
  echo "Invalid model tag in ${MODEL_OVERRIDE_FILE} or OLLAMA_MODEL" >&2
  exit 1
fi
printf '%s\n' "${MODEL}"
