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

readonly MODEL_OVERRIDE_FILE="/config/.opencode-model"
readonly DEFAULT_MODEL="nemotron-3.5-lightning:30b"

if [[ -s "${MODEL_OVERRIDE_FILE}" ]]; then
  tr -d '[:space:]' < "${MODEL_OVERRIDE_FILE}"
else
  echo "${OLLAMA_MODEL:-${DEFAULT_MODEL}}"
fi
