#!/bin/sh
# Aevom refuses to start without at least one LLM API key. Wait for the user
# to add one with `aevom key ...` in the code-server terminal, then start.
set -eu

export VERSION_NUMBER="$(cat /tmp/version 2>/dev/null || echo 0.0.0-dev)"

has_key() {
  for f in /run/aevom-keys/API_KEY_NV /run/aevom-keys/API_KEY_NVINF \
           /run/aevom-keys/API_KEY_ANTHROPIC /run/aevom-keys/API_KEY_OPENAI; do
    [ -s "$f" ] && return 0
  done
  return 1
}

n=0
until has_key; do
  if [ $((n % 12)) -eq 0 ]; then
    echo "aevom-api: waiting for an LLM API key. In the code-server terminal run: aevom key nv"
  fi
  n=$((n + 1))
  sleep 5
done

echo "aevom-api: key present, starting (model: ${AEVOM_MODEL:-default})"
exec "$@"
