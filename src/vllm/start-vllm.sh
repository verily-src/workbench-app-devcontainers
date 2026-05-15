#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

OLLAMA_LOG="/config/ollama-server.log"

nohup ollama serve > "${OLLAMA_LOG}" 2>&1 &
sleep 2

echo "Pulling google/gemma-4-E4B-it model (this may take a few minutes)..."
ollama pull gemma4:4b >> "${OLLAMA_LOG}" 2>&1

echo "Ollama ready — logs at ${OLLAMA_LOG}"
