#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if docker compose version >/dev/null 2>&1; then
  exec docker compose -f "${ROOT}/compose.local.yaml" "$@"
fi
if command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose -f "${ROOT}/compose.local.yaml" "$@"
fi
printf 'Docker Compose is required. Install the Docker Compose CLI plugin or standalone command.\n' >&2
exit 2
