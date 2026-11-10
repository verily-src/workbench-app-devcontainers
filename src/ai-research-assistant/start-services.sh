#!/bin/bash

# Lifecycle hooks run as root after Workbench authentication and mounts.
set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1:?Usage: start-services.sh <username> <user-home-dir>}"
readonly USER_HOME_DIR="${2:?Usage: start-services.sh <username> <user-home-dir>}"
# This script is bind-mounted alone from the app folder (docker-compose.yaml); everything it
# starts is a feature installed in the image.
export APP_USER_HOME="${USER_HOME_DIR}"

# vLLM runs as the user: its state, compile cache, model store and log must be
# user-owned, including on upgrade from an app that created them as root.
mkdir -p "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache"
touch "${USER_HOME_DIR}/vllm-server.log"
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache"
chown "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/vllm-server.log"

# As the authenticated user, so the MCP server and the context see the user's wb tokens.
sudo -H -u "${USER_NAME}" /opt/wb-mcp-server/start-server.sh
sudo -H -u "${USER_NAME}" /opt/llm-context/run-context-generator.sh "${USER_HOME_DIR}" || {
  echo "Workbench context generation failed; run generate-llm-context after logging in." >&2
}

# Preserve vLLM settings across sudo; keep logs and cached weights user-owned.
sudo -H -u "${USER_NAME}" \
  --preserve-env=APP_USER_HOME,VLLM_GPU_MEMORY_MIB,VLLM_MODEL_STORE_SEARCH,VLLM_MODEL,VLLM_PORT,VLLM_BIND_ADDRESS,VLLM_MODELS,VLLM_CONTEXT_LENGTH,VLLM_GPU_MEMORY_UTILIZATION,VLLM_MAX_NUM_SEQS,VLLM_LOAD_TIMEOUT_MINUTES,VLLM_EXTRA_ARGS,VLLM_HTTP_TIMEOUT_KEEP_ALIVE \
  /opt/vllm-model/start-vllm.sh

# Publish the user's key for the sandbox-broker now, so the first command does not wait on it.
sudo -H -u "${USER_NAME}" --preserve-env=APP_USER_HOME bash -c '
  set -e
  key="${APP_USER_HOME}/.ssh/sandbox-broker"
  if [[ ! -f "${key}" ]]; then
    mkdir -p "${APP_USER_HOME}/.ssh" && chmod 700 "${APP_USER_HOME}/.ssh"
    ssh-keygen -q -t ed25519 -N "" -C sandbox-broker -f "${key}"
  fi
  mkdir -p "${APP_USER_HOME}/openshell"
  install -m 644 "${key}.pub" "${APP_USER_HOME}/openshell/broker.pub"'
# Create the sandbox and forward its web UI now, so opening the app does not wait on a first
# `opencode`. Best effort: any later agent-sandbox command re-establishes the forward.
if ! sudo -H -u "${USER_NAME}" --preserve-env=APP_USER_HOME,AGENT_BROKER,AGENT_MODEL_COMMAND,VLLM_MODEL \
    /usr/local/bin/agent-sandbox web; then
  echo "The web UI is not up yet; run \`agent-sandbox web\` in a terminal." >&2
fi
