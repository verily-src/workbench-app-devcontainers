#!/bin/bash
# entrypoint.sh
#
# The Spring Boot app is the container's PID 1, started immediately when the
# container boots. But Workbench-specific values (OWNER_EMAIL, GOOGLE_PROJECT,
# WORKBENCH_USER_EMAIL, ...) aren't known yet at that point -- they're fetched
# by post-startup.sh (via postCreateCommand, see .devcontainer.json) only
# after the container is already running, and written to the app user's
# ~/.bashrc (/home/via/.bashrc).
#
# postCreateCommand extracts those exports into /home/via/.workbench-env once
# post-startup.sh finishes (same approach used by other Workbench app
# templates upstream, e.g. aou-sas/setup-sas-env.sh).
# Wait for that file here, then source it before starting the app, so
# System.getenv() in the Java process actually sees these values.
#
# This runs as the unprivileged `via` user (see deploy/Dockerfile), so HOME
# is /home/via -- the same path .devcontainer.json's postCreateCommand writes to.
set -euo pipefail

readonly WORKBENCH_ENV_FILE="${HOME}/.workbench-env"
# post-startup.sh (wb CLI download/login, git-setup, gcsfuse install/mount) has
# been observed taking ~3 minutes on a fresh VM; give it comfortable headroom.
readonly MAX_WAIT_SECONDS=600

if [[ "${SKIP_WORKBENCH_WAIT:-false}" == "true" ]]; then
  echo "SKIP_WORKBENCH_WAIT=true; not waiting for ${WORKBENCH_ENV_FILE} (local dev mode)." >&2
else
  waited=0
  while [[ ! -f "${WORKBENCH_ENV_FILE}" && "${waited}" -lt "${MAX_WAIT_SECONDS}" ]]; do
    sleep 1
    waited=$((waited + 1))
  done

  if [[ -f "${WORKBENCH_ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${WORKBENCH_ENV_FILE}"
  else
    echo "WARNING: ${WORKBENCH_ENV_FILE} not found after ${MAX_WAIT_SECONDS}s; starting without Workbench environment variables." >&2
  fi
fi

# docker-compose.yaml passes WORKSPACE_CDR through as an empty string when the VM doesn't set it,
# and Spring treats an empty value as set, skipping application.properties' default. So drop empty
# ones and let the defaults apply -- but say so, since in a real workspace these should be the
# workspace's own values, and the defaults point at the dev project's synthetic data.
for var in WORKSPACE_CDR GOOGLE_PROJECT; do
  if [[ -z "${!var:-}" ]]; then
    unset "${var}"
    echo "WARNING: ${var} is not set; using its default from application.properties." >&2
  fi
done

exec java -jar /app/app.jar
