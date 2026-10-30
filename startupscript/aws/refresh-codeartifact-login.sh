#!/bin/bash

# Installed by configure-codeartifact.sh and run as the app user. Uses the
# instance role to renew pip/npm credentials in the user's config files.
# No arguments: refresh once. --start: refresh and launch one background worker.
# Results log to ~/.workbench/codeartifact-refresh.log and stdout; the startup
# hooks point stdout at the container log so fluent-bit ships it. The worker
# keeps --start's stdout open, so callers must redirect it to a file or fd,
# never capture it with a command substitution or pipe.
# Internal --loop mode renews every six hours and retries failures after five minutes.
set -o errexit
set -o nounset
set -o pipefail
umask 077

source /etc/workbench-codeartifact.conf

readonly STATE_DIR="${CODEARTIFACT_USER_HOME}/.workbench"
readonly REFRESH_INTERVAL=21600 # Six hours, halfway through the token lifetime.
readonly RETRY_INTERVAL=300
readonly LOG_FILE="${STATE_DIR}/codeartifact-refresh.log"
mkdir -p "${STATE_DIR}"

# Authenticate with the instance role, not the user's workspace credentials.
# Only affects this process.
unset AWS_PROFILE
unset AWS_DEFAULT_PROFILE
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN
unset AWS_SECURITY_TOKEN
unset AWS_ROLE_ARN
unset AWS_ROLE_SESSION_NAME
unset AWS_WEB_IDENTITY_TOKEN_FILE
unset AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
unset AWS_CONTAINER_CREDENTIALS_FULL_URI
unset AWS_CONTAINER_AUTHORIZATION_TOKEN
unset AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE
export AWS_CONFIG_FILE=/dev/null
export AWS_SHARED_CREDENTIALS_FILE=/dev/null
export BOTO_CONFIG=/dev/null
export AWS_EC2_METADATA_DISABLED=false
export AWS_EC2_METADATA_SERVICE_ENDPOINT=http://169.254.169.254
export AWS_CLI_AUTO_PROMPT=off
export AWS_PAGER=""

# Write the user-level configs, even from a virtualenv or with config overrides.
unset PIP_CONFIG_FILE
unset PIP_GLOBAL
unset PIP_SITE
unset npm_config_userconfig
export PIP_USER=true
export NPM_CONFIG_USERCONFIG="${CODEARTIFACT_USER_HOME}/.npmrc"
readonly PIP_CONFIG="${XDG_CONFIG_HOME:-${CODEARTIFACT_USER_HOME}/.config}/pip/pip.conf"

# sudo/login shells can drop the Node feature's container PATH. Use its stable
# symlink without relying on interactive nvm initialization or changing users.
readonly NVM_BIN="${NVM_DIR:-/usr/local/share/nvm}/current/bin"
if ! command -v node > /dev/null || ! command -v npm > /dev/null; then
  if [[ -x "${NVM_BIN}/node" && -x "${NVM_BIN}/npm" ]]; then
    export PATH="${NVM_BIN}:${PATH}"
  fi
fi

log() {
  local line
  line="$(date -u): $*"
  echo "${line}"
  # An unwritable log file must not kill a refresh; stdout still gets the line.
  echo "${line}" >> "${LOG_FILE}" 2>/dev/null || true
}

retry() {
  local attempt
  for ((attempt = 1; attempt <= 5; attempt++)); do
    if "${@}"; then
      return 0
    fi
    if ((attempt < 5)); then
      sleep 5
    fi
  done
  return 1
}

refresh() (
  # Manual, startup and periodic refreshes write the same files.
  exec 8> "${STATE_DIR}/codeartifact-login.lock"
  flock -w 120 8 || return 1
  mkdir -p "$(dirname "${PIP_CONFIG}")" || return 1
  touch "${NPM_CONFIG_USERCONFIG}" "${PIP_CONFIG}" || return 1
  chmod 600 "${NPM_CONFIG_USERCONFIG}" "${PIP_CONFIG}" || return 1

  local status=0
  # Attempt both logins even if one package manager fails.
  local spec tool repository
  for spec in npm:npm-mirror pip:pypi-mirror; do
    tool="${spec%%:*}"
    repository="${spec#*:}"
    if retry aws codeartifact login --tool "${tool}" \
      --domain "${CODEARTIFACT_DOMAIN}" --domain-owner "${CODEARTIFACT_OWNER}" \
      --repository "${repository}" --region "${CODEARTIFACT_REGION}" --duration-seconds 43200; then
      log "CodeArtifact ${tool} token refreshed"
    else
      log "WARNING: CodeArtifact ${tool} token refresh failed"
      status=1
    fi
  done
  # The login may recreate the files with default permissions.
  chmod 600 "${NPM_CONFIG_USERCONFIG}" "${PIP_CONFIG}" || status=1
  return "${status}"
)

case "${1:-}" in
  "")
    refresh
    ;;
  --start)
    # Refresh before returning so the app is ready with valid tokens.
    status=0
    delay="${REFRESH_INTERVAL}"
    refresh || status=$?
    if ((status != 0)); then
      delay="${RETRY_INTERVAL}"
    fi
    # Outlives the lifecycle hook. Its lock dies with the container, so
    # postStart can start a new one. It inherits --start's stdout so its
    # results reach the container log.
    nohup "$0" --loop "${delay}" < /dev/null 2>&1 &
    exit "${status}"
    ;;
  --loop)
    # One worker at a time. Children close fd 9 so an orphaned sleep can't
    # hold the lock after the worker is killed.
    exec 9> "${STATE_DIR}/codeartifact-refresh.lock"
    flock -n 9 || exit 0
    delay="${2:-${REFRESH_INTERVAL}}"
    while sleep "${delay}" 9>&-; do
      delay="${REFRESH_INTERVAL}"
      if ! (
        # The parent worker keeps the lock; this child releases its copy.
        exec 9>&-
        refresh
      ); then
        log "Retrying CodeArtifact refresh in ${RETRY_INTERVAL} seconds"
        delay="${RETRY_INTERVAL}"
      fi
    done
    ;;
  *)
    echo "Usage: $0 [--start]" >&2
    exit 2
    ;;
esac
