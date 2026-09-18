#!/bin/bash

# Lifecycle hooks run as root after Workbench authentication and mounts.
set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1:?Usage: start-services.sh <username> <user-home-dir>}"
readonly USER_HOME_DIR="${2:?Usage: start-services.sh <username> <user-home-dir>}"
SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
export OPENCODE_HOME="${USER_HOME_DIR}"

# Earlier versions started Ollama as root. Repair the persistent cache/log once
# on upgrade so a user-run model switch can reuse them.
mkdir -p "${USER_HOME_DIR}/.ollama"
touch "${USER_HOME_DIR}/ollama-server.log"
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/.ollama"
chown "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/ollama-server.log"

"${SCRIPT_DIR}/configure-opencode.sh" "${USER_NAME}" "${USER_HOME_DIR}"

# Run as the authenticated user so MCP and context see the user's wb tokens.
sudo -H -u "${USER_NAME}" /opt/wb-mcp-server/start-server.sh
sudo -H -u "${USER_NAME}" /opt/llm-context/run-context-generator.sh "${USER_HOME_DIR}" || {
  echo "Workbench context generation failed; run generate-llm-context after logging in." >&2
}

# Preserve Ollama settings across sudo; keep logs and cached weights user-owned.
sudo -H -u "${USER_NAME}" \
  --preserve-env=OPENCODE_HOME,OLLAMA_MODEL,OLLAMA_HOST,OLLAMA_MODELS,OLLAMA_KEEP_ALIVE,OLLAMA_FLASH_ATTENTION,OLLAMA_CONTEXT_LENGTH,OLLAMA_NUM_PARALLEL,OLLAMA_MAX_LOADED_MODELS \
  "${SCRIPT_DIR}/start-ollama.sh"
