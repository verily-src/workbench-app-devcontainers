#!/bin/bash

# sshd's ForceCommand on the sandbox-broker (the agent-sandbox README, "Admin-locked mode"): the only thing a
# connection from the app can run. Decodes the argument list broker-client.sh sent, one base64
# string of NUL-separated words, allows a fixed set of agent-sandbox commands, and runs
# agent-sandbox with this image's policy files. Nothing the client sent is evaluated as shell.
# The model comes from the client (AGENT_MODEL_OVERRIDE); the broker has no GPU to choose one.

set -o errexit
set -o nounset
set -o pipefail

die() {
  echo "sandbox-broker: $*" >&2
  exit 1
}

# The feature this script ships with: /opt/agent-sandbox in the image.
FRAMEWORK_DIR="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")"
readonly FRAMEWORK_DIR

# What the entrypoint recorded of the container's environment; sshd starts sessions clean.
# shellcheck source=/dev/null
[[ -f /etc/sandbox-broker.env ]] && source /etc/sandbox-broker.env
export APP_USER_HOME="${APP_USER_HOME:-/config}"
export HOME="${APP_USER_HOME}"
unset AGENT_SANDBOX_CONFIG AGENT_MODEL AGENT_MODEL_COMMAND

encoded="${SSH_ORIGINAL_COMMAND:-}"
[[ "${encoded}" =~ ^[A-Za-z0-9+/=]*$ ]] || die "malformed request"
args=()
if [[ -n "${encoded}" ]]; then
  mapfile -d '' -t args < <(printf '%s' "${encoded}" | base64 -d)
fi

# The model comes first, resolved in the app where the GPU is.
if [[ "${args[0]:-}" == __model=* ]]; then
  model="${args[0]#__model=}"
  [[ "${model}" =~ ^[[:alnum:]][[:alnum:]_.:/-]*$ ]] || die "invalid model tag"
  export AGENT_MODEL_OVERRIDE="${model}"
  args=("${args[@]:1}")
fi

case "${args[0]:-run}" in
  run|shell|exec|upload|download|status|web|policy|logs|reset|selftest|credential|-h|--help|help) ;;
  audit) [[ "${args[1]:-}" == save ]] || die "audit export runs in the app, which copies to the bucket" ;;
  *) die "not available through the broker: ${args[0]}" ;;
esac

cd "${APP_USER_HOME}"
exec "${FRAMEWORK_DIR}/agent-sandbox.sh" ${args[@]+"${args[@]}"}
