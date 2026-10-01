#!/bin/bash

# Installed by configure-codeartifact.sh and run as the app user. Uses the
# instance role to renew pip/npm credentials in the user's config files.
# No arguments: refresh once. --start: refresh and launch one background worker.
# Internal --loop mode renews every six hours and retries failures after five minutes.
set -o errexit
set -o nounset
set -o pipefail
umask 077

source /etc/workbench-codeartifact.conf

readonly STATE_DIR="${CODEARTIFACT_USER_HOME}/.workbench"
readonly REFRESH_INTERVAL=21600 # Six hours, halfway through the token lifetime.
readonly RETRY_INTERVAL=300
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
  retry aws codeartifact login --tool npm \
    --domain "${CODEARTIFACT_DOMAIN}" --domain-owner "${CODEARTIFACT_OWNER}" \
    --repository npm-mirror --region "${CODEARTIFACT_REGION}" --duration-seconds 43200 || status=1
  retry aws codeartifact login --tool pip \
    --domain "${CODEARTIFACT_DOMAIN}" --domain-owner "${CODEARTIFACT_OWNER}" \
    --repository pypi-mirror --region "${CODEARTIFACT_REGION}" --duration-seconds 43200 || status=1
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
    # postStart can start a new one.
    nohup "$0" --loop "${delay}" < /dev/null >> "${STATE_DIR}/codeartifact-refresh.log" 2>&1 &
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
        echo "$(date -u): WARNING: CodeArtifact refresh failed; retrying in ${RETRY_INTERVAL} seconds" >&2
        delay="${RETRY_INTERVAL}"
      fi
    done
    ;;
  *)
    echo "Usage: $0 [--start]" >&2
    exit 2
    ;;
esac
