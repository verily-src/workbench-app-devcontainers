#!/bin/bash

# The app's side of the sandbox-broker (README, "Admin-locked mode"): agent-sandbox.sh hands
# every command here when AGENT_BROKER is set. The argument list travels as one base64 string
# of NUL-separated words, so the broker evaluates nothing we send as shell. The model is
# resolved here, where the GPU is, and sent first. `audit export` is split in two: the broker
# saves, this side copies to the bucket with gcloud, which the broker does not have.

set -o errexit
set -o nounset
set -o pipefail

readonly USER_HOME_DIR="${APP_USER_HOME:-/config}"
readonly BROKER="${AGENT_BROKER:?AGENT_BROKER names the sandbox broker}"
readonly KEY="${USER_HOME_DIR}/.ssh/sandbox-broker"
readonly KNOWN_HOSTS="${USER_HOME_DIR}/.ssh/sandbox-broker.known_hosts"
# The broker reads our public key from the shared home (broker/authorized-keys.sh).
readonly PUBLISHED_KEY="${USER_HOME_DIR}/openshell/broker.pub"

die() {
  echo "agent-sandbox: $*" >&2
  exit 1
}

# A key of our own, published where the broker looks. Anyone in this container can read it,
# which is fine: it opens only the broker's fixed command, never a shell there.
ensure_key() {
  if [[ ! -f "${KEY}" ]]; then
    mkdir -p "${USER_HOME_DIR}/.ssh"
    chmod 700 "${USER_HOME_DIR}/.ssh"
    ssh-keygen -q -t ed25519 -N '' -C sandbox-broker -f "${KEY}"
  fi
  mkdir -p "${USER_HOME_DIR}/openshell"
  if ! cmp -s "${KEY}.pub" "${PUBLISHED_KEY}"; then
    install -m 644 "${KEY}.pub" "${PUBLISHED_KEY}"
  fi
}

# The model: AGENT_MODEL, or what AGENT_MODEL_COMMAND prints.
model() {
  if [[ -n "${AGENT_MODEL:-}" ]]; then
    printf '%s\n' "${AGENT_MODEL}"
    return 0
  fi
  [[ -n "${AGENT_MODEL_COMMAND:-}" ]] || die "no model: set AGENT_MODEL, or AGENT_MODEL_COMMAND to a command that prints it"
  APP_USER_HOME="${USER_HOME_DIR}" ${AGENT_MODEL_COMMAND}
}

encode() {
  printf '%s\0' "$@" | base64 -w0
}

ssh_opts=(
  -o LogLevel=ERROR -i "${KEY}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="${KNOWN_HOSTS}" -o ConnectTimeout=15 -o ServerAliveInterval=30
)

# Runs the command on the broker, with a terminal if we have one.
remote() {
  local tty=-T
  [[ -t 0 && -t 1 ]] && tty=-t
  exec ssh "${tty}" "${ssh_opts[@]}" "abc@${BROKER}" -- "$(encode "$@")"
}

main() {
  ensure_key
  local model_tag
  model_tag="$(model)"
  if [[ "${1:-}" == audit && "${2:-}" == export ]]; then
    local dest="${3:-}"
    [[ "${dest}" =~ ^gs://[a-z0-9][a-z0-9._-]*(/.*)?$ ]] || die "usage: agent-sandbox audit export gs://<bucket>[/<folder>]"
    local saved files=()
    saved="$(ssh -T "${ssh_opts[@]}" "abc@${BROKER}" -- "$(encode "__model=${model_tag}" audit save)")"
    [[ -n "${saved}" ]] || die "nothing to export"
    mapfile -t files <<< "${saved}"
    gcloud storage cp "${files[@]}" "${dest%/}/"
    return 0
  fi
  remote "__model=${model_tag}" "$@"
}

main "$@"
