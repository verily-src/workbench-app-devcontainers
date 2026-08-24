#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

readonly OLLAMA_LOG="/config/ollama-server.log"
readonly OLLAMA_URL="http://localhost:11434"
readonly MODEL="${OLLAMA_MODEL:-nemotron-3.5-lightning:30b}"

server_is_up() {
  curl -fsS "${OLLAMA_URL}/api/version" > /dev/null 2>&1
}

# postCreateCommand and postStartCommand both run on first start, so only start
# the server if it is not already listening.
if ! server_is_up; then
  nohup ollama serve > "${OLLAMA_LOG}" 2>&1 &

  for _ in $(seq 30); do
    if server_is_up; then
      break
    fi
    sleep 2
  done

  if ! server_is_up; then
    echo "Ollama did not start — see ${OLLAMA_LOG}" >&2
    exit 1
  fi
fi

echo "Pulling ${MODEL} (this may take several minutes)..."
ollama pull "${MODEL}" >> "${OLLAMA_LOG}" 2>&1

echo "Preloading ${MODEL} into GPU memory..."
curl -fsS "${OLLAMA_URL}/api/generate" \
  -d "{\"model\":\"${MODEL}\",\"prompt\":\"warmup\",\"options\":{\"num_predict\":1}}" > /dev/null

echo "Ollama ready with ${MODEL} — logs at ${OLLAMA_LOG}"
