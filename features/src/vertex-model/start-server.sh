#!/bin/bash

# Starts the Vertex AI model server (proxy.py) on vLLM's port as this user, waits for it, and sends
# the model one short request so a missing permission shows here rather than in the agent's first
# turn. Settings: VERTEX_MODEL, VERTEX_ENDPOINT_URL (the workspace's endpoint, in place of Gemini),
# VERTEX_LOCATION, GOOGLE_CLOUD_PROJECT, VLLM_PORT, VLLM_BIND_ADDRESS, VLLM_CONTEXT_LENGTH
# (README.md).

set -o errexit
set -o nounset
set -o pipefail

readonly DIR="/opt/vertex-model"
readonly MODEL="${VERTEX_MODEL:?VERTEX_MODEL names the model to serve (start-services.sh sets it)}"
readonly SOURCE="${VERTEX_ENDPOINT_URL:-Gemini on Vertex AI}"
readonly PORT="${VLLM_PORT:-8000}"
readonly URL="http://127.0.0.1:${PORT}"
readonly STATE="${HOME}/.vertex-model"
readonly LOG="${STATE}/server.log"

served_model() {
  curl -fsS --connect-timeout 2 --max-time 5 "${URL}/v1/models" 2> /dev/null | jq -r '.data[0].id' 2> /dev/null || true
}

mkdir -p "${STATE}"
# postCreateCommand and postStartCommand both run on first start.
if [[ "$(served_model)" == "${MODEL}" ]]; then
  echo "Vertex AI already serves ${MODEL} on port ${PORT}."
  exit 0
fi
if curl -fsS --connect-timeout 2 --max-time 5 "${URL}/health" > /dev/null 2>&1; then
  echo "Another server answers on port ${PORT}; stop it first." >&2
  exit 1
fi

nohup python3 "${DIR}/proxy.py" >> "${LOG}" 2>&1 &
for _ in $(seq 30); do
  [[ "$(served_model)" == "${MODEL}" ]] && break
  sleep 1
done
if [[ "$(served_model)" != "${MODEL}" ]]; then
  echo "The Vertex AI model server did not start; see ${LOG}." >&2
  exit 1
fi

reply="$(curl -sS --max-time 120 -H "Content-Type: application/json" "${URL}/v1/chat/completions" \
  -d "{\"model\": \"${MODEL}\", \"max_tokens\": 16, \"messages\": [{\"role\": \"user\", \"content\": \"Say ok.\"}]}" 2>&1 || true)"
if jq -e '.choices[0]' > /dev/null 2>&1 <<< "${reply}"; then
  echo "Serving ${MODEL} from ${SOURCE} on port ${PORT}. Logs: ${LOG}"
else
  said="$(jq -r '.error.message? // .[0].error.message? // .' <<< "${reply}" 2> /dev/null || printf '%s' "${reply}")"
  echo "Serving ${MODEL} on port ${PORT}, but ${SOURCE} refused a test request; the VM's service account needs roles/aiplatform.user (an endpoint whose replica is still starting, or is overloaded, can answer 429). It said: ${said:0:400}" >&2
fi
