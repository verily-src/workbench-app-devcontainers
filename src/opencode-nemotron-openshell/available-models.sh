#!/bin/bash

# Prints the catalog entries that fit on the largest attached GPU. Capacity is
# used instead of product names so provider-specific labels do not affect the
# result. OPENCODE_GPU_MEMORY_MIB is an explicit override for tests/operators.
set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
readonly CATALOG="${SCRIPT_DIR}/models.json"

if [[ -n "${OPENCODE_GPU_MEMORY_MIB:-}" ]]; then
  GPU_MEMORY_MIB="${OPENCODE_GPU_MEMORY_MIB}"
else
  if ! command -v nvidia-smi > /dev/null 2>&1; then
    echo "Cannot determine GPU memory: nvidia-smi is unavailable." >&2
    exit 1
  fi
  GPU_MEMORY_MIB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits |
    awk 'BEGIN { max = 0 } $1 + 0 > max { max = $1 + 0 } END { if (max > 0) print max }')"
fi

if [[ ! "${GPU_MEMORY_MIB}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Cannot determine GPU memory: expected a positive MiB value, got '${GPU_MEMORY_MIB}'." >&2
  exit 1
fi

AVAILABLE="$(jq --argjson memory "${GPU_MEMORY_MIB}" \
  '[.[] | select(.minimum_vram_mib <= $memory)]' "${CATALOG}")"
if [[ "$(jq 'length' <<< "${AVAILABLE}")" == "0" ]]; then
  echo "No supported model fits the detected ${GPU_MEMORY_MIB} MiB of GPU memory." >&2
  exit 1
fi

printf '%s\n' "${AVAILABLE}"
