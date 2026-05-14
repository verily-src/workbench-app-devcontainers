#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

VLLM_LOG="/config/vllm-server.log"

echo "Starting vLLM server on port 8000..."
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    echo "GPU detected — using GPU backend"
    nohup python -m vllm.entrypoints.openai.api_server \
        --model meta-llama/Llama-3.2-3B-Instruct \
        --host 0.0.0.0 \
        --port 8000 \
        --max-model-len 4096 \
        --dtype half \
        --gpu-memory-utilization 0.90 \
        > "${VLLM_LOG}" 2>&1 &
else
    echo "No GPU detected — using CPU backend (this will be slow)"
    nohup python -m vllm.entrypoints.openai.api_server \
        --model meta-llama/Llama-3.2-3B-Instruct \
        --host 0.0.0.0 \
        --port 8000 \
        --max-model-len 2048 \
        --device cpu \
        --dtype bfloat16 \
        > "${VLLM_LOG}" 2>&1 &
fi

echo "vLLM PID: $! — logs at ${VLLM_LOG}"
