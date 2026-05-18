#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

OLLAMA_LOG="/config/ollama-server.log"

nohup ollama serve > "${OLLAMA_LOG}" 2>&1 &
sleep 2

echo "Pulling gemma4:26b model (this may take a few minutes)..."
ollama pull gemma4:26b >> "${OLLAMA_LOG}" 2>&1

echo "Preloading model into GPU memory..."
curl -s http://localhost:11434/api/generate -d '{"model":"gemma4:26b","prompt":"warmup","options":{"num_predict":1}}' > /dev/null 2>&1

echo "Ollama ready — model loaded — logs at ${OLLAMA_LOG}"
