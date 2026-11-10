#!/bin/bash

# Prints the Hugging Face model ID that the app must serve with vLLM: VLLM_MODEL
# from the app's compose file.

set -o errexit
set -o nounset
set -o pipefail

readonly MODEL="${VLLM_MODEL:?VLLM_MODEL names the model to serve (the compose file of the app sets it)}"

# IDs are org/name on Hugging Face, or a local directory name under the model store.
if [[ ! "${MODEL}" =~ ^[[:alnum:]][[:alnum:]_.:/-]*$ ]]; then
  echo "Invalid model ID in VLLM_MODEL: ${MODEL}" >&2
  exit 1
fi
printf '%s\n' "${MODEL}"
