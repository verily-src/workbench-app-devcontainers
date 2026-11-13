#!/bin/bash

# Build the actual image plus every configured devcontainer feature. Lifecycle
# hooks require Workbench credentials/GPU and are exercised on the real VM.
set -o errexit
set -o nounset
set -o pipefail

STAGE_DIR="$(mktemp -d)"
readonly STAGE_DIR
cp -a src/opencode-nemotron-mcp/. "${STAGE_DIR}/"
mkdir -p "${STAGE_DIR}/.devcontainer/features"
cp -a features/src/. "${STAGE_DIR}/.devcontainer/features/"
cp -a startupscript "${STAGE_DIR}/startupscript"
# Workbench placeholders are literal strings, not shell variables.
# shellcheck disable=SC2016
sed -i 's/${templateOption:cloud}/gcp/g; s/${templateOption:login}/false/g' "${STAGE_DIR}/.devcontainer.json"
startupscript/butane/prefetch-oci-features.sh "${STAGE_DIR}/.devcontainer.json"
devcontainer build --workspace-folder "${STAGE_DIR}" --image-name opencode-nemotron-mcp:ci

# Run as the real unprivileged image user; install paths and ownership matter.
docker run --rm --user abc --entrypoint python3 \
  -v "${PWD}/tests/opencode-nemotron-mcp:/tests:ro" \
  opencode-nemotron-mcp:ci /tests/container_smoke.py
