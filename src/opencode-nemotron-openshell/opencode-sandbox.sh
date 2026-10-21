#!/bin/bash

# Runs OpenCode in an NVIDIA OpenShell sandbox and manages that sandbox.
#
# The sandbox holds no credentials and can reach only what the policy in
# /config/openshell/policy.yaml allows: by default, Ollama's chat API for the
# local Nemotron models. Every connection it makes is checked and logged by
# OpenShell. See README.md, "Sandboxed OpenCode".

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
readonly USER_HOME_DIR="${OPENCODE_HOME:-/config}"
readonly SANDBOX_NAME="${OPENCODE_SANDBOX_NAME:-opencode-agent}"
readonly SANDBOX_IMAGE="${OPENCODE_SANDBOX_IMAGE:-opencode-agent-sandbox:0.1}"
readonly SANDBOX_WORKDIR="/sandbox/work"
readonly DEFAULT_POLICY="${SCRIPT_DIR}/openshell/policy.yaml"
readonly POLICY="${USER_HOME_DIR}/openshell/policy.yaml"
readonly DOWNLOAD_DIR="${USER_HOME_DIR}/sandbox-downloads"
# The sandbox reaches the app's Ollama through the VM's loopback.
readonly SANDBOX_OLLAMA_URL="http://host.openshell.internal:11434/v1"
readonly CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"

export OPENSHELL_GATEWAY_ENDPOINT="${OPENSHELL_GATEWAY_ENDPOINT:-http://openshell-gateway:8080}"
export OPENSHELL_TELEMETRY_ENABLED=false
export NO_COLOR=1

usage() {
  cat <<EOF
Usage: opencode-sandbox <command> [arguments]

  run [opencode args]      Start OpenCode in the sandbox (what \`opencode\` does)
  shell                    Open a shell in the sandbox
  upload <path> [dest]     Copy files into the sandbox (default: ${SANDBOX_WORKDIR})
  download <path> [dest]   Copy files out of the sandbox (default: ${DOWNLOAD_DIR})
  status                   Show the gateway, the sandbox and the policy file
  policy                   Apply ${POLICY} to the running sandbox
  logs [count]             Show the sandbox's recent network decisions (default 100)
  rules                    List rules OpenShell drafted from blocked connections
  approve <chunk-id>       Approve a drafted rule for this sandbox
  reject <chunk-id>        Reject a drafted rule
  reset --yes              Delete the sandbox and its files, then create a new one
  selftest                 Check the sandbox's isolation and model access
EOF
}

die() {
  echo "opencode-sandbox: $*" >&2
  exit 1
}

wait_for_gateway() {
  local attempt
  for attempt in $(seq 30); do
    if openshell status > /dev/null 2>&1; then
      return 0
    fi
    if (( attempt == 1 )); then
      echo "Waiting for the OpenShell gateway at ${OPENSHELL_GATEWAY_ENDPOINT}..." >&2
    fi
    sleep 2
  done
  die "the OpenShell gateway is not reachable. On the VM, check: docker logs openshell-gateway"
}

ensure_policy() {
  if [[ ! -s "${POLICY}" ]]; then
    mkdir -p "$(dirname "${POLICY}")"
    cp "${DEFAULT_POLICY}" "${POLICY}"
    echo "Wrote the default sandbox policy to ${POLICY}" >&2
  fi
}

sandbox_phase() {
  openshell sandbox get "${SANDBOX_NAME}" -o json 2> /dev/null |
    jq -r '[.. | objects | .phase? | strings] | first // "unknown"' 2> /dev/null || true
}

ensure_sandbox() {
  wait_for_gateway
  ensure_policy
  if ! openshell sandbox get "${SANDBOX_NAME}" > /dev/null 2>&1; then
    echo "Creating sandbox ${SANDBOX_NAME} from ${SANDBOX_IMAGE} with ${POLICY}..." >&2
    # No trailing command: OpenShell keeps a login shell running, and OpenCode
    # starts with `sandbox exec`. Proposals for blocked connections always wait
    # for a person (--approval-mode manual).
    openshell sandbox create --name "${SANDBOX_NAME}" --from "${SANDBOX_IMAGE}" \
      --policy "${POLICY}" --no-auto-providers --no-tty --detach \
      --approval-mode manual --label app=opencode-nemotron > /dev/null
    return 0
  fi
  case "$(sandbox_phase)" in
    Stopped|stopped|STOPPED)
      echo "Starting stopped sandbox ${SANDBOX_NAME}..." >&2
      openshell sandbox start "${SANDBOX_NAME}" > /dev/null
      ;;
  esac
}

# OpenCode config for the sandbox: local Ollama only, no MCP servers, no
# sharing or updates, and no web fetches (the policy would block them anyway).
sandbox_config() {
  local model available models
  model="$(OPENCODE_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/resolve-model.sh")"
  if [[ "${model}" == "prompt" ]]; then
    "${SCRIPT_DIR}/opencode-model.sh" >&2
    model="$(OPENCODE_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/resolve-model.sh")"
  fi
  available="$("${SCRIPT_DIR}/available-models.sh")"
  models="$(jq --argjson context "${CONTEXT_LENGTH}" \
    'reduce .[] as $entry ({}; .[$entry.tag] = {
      name: $entry.name,
      limit: {context: $context, output: 8192}
    })' <<< "${available}")"
  if ! jq -e --arg model "${model}" 'has($model)' <<< "${models}" > /dev/null; then
    models="$(jq --arg model "${model}" --argjson context "${CONTEXT_LENGTH}" \
      '.[$model] = {name: $model, limit: {context: $context, output: 8192}}' <<< "${models}")"
  fi
  jq -nc --arg model "${model}" --arg url "${SANDBOX_OLLAMA_URL}" --argjson models "${models}" '{
    "$schema": "https://opencode.ai/config.json",
    "model": ("ollama/" + $model),
    "small_model": ("ollama/" + $model),
    "enabled_providers": ["ollama"],
    "autoupdate": false,
    "share": "disabled",
    "instructions": ["/opt/opencode-sandbox/instructions.md"],
    "permission": {"webfetch": "deny"},
    "provider": {
      "ollama": {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Ollama (local)",
        "options": {"baseURL": $url},
        "models": $models
      }
    }
  }'
}

# Runs OpenCode in the sandbox with the config passed in the environment. The
# config is base64-encoded so it survives the remote command line unchanged.
exec_opencode() {
  local tty_flag="$1"
  shift
  local config
  config="$(sandbox_config | base64 -w0)"
  # shellcheck disable=SC2016 # Expanded inside the sandbox, not here.
  openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" "${tty_flag}" -- \
    bash -c 'export OPENCODE_CONFIG_CONTENT="$(printf %s "$1" | base64 -d)"; shift; exec opencode "$@"' \
    opencode-sandbox "${config}" "$@"
}

cmd_run() {
  ensure_sandbox
  exec_opencode --tty "$@"
}

cmd_shell() {
  ensure_sandbox
  exec openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" --tty -- bash -l
}

cmd_upload() {
  (( $# >= 1 && $# <= 2 )) || die "usage: opencode-sandbox upload <path> [dest]"
  ensure_sandbox
  openshell sandbox upload "${SANDBOX_NAME}" "$1" "${2:-${SANDBOX_WORKDIR}}"
}

cmd_download() {
  (( $# >= 1 && $# <= 2 )) || die "usage: opencode-sandbox download <path> [dest]"
  ensure_sandbox
  local source="$1"
  if [[ "${source}" != /* ]]; then
    source="${SANDBOX_WORKDIR}/${source}"
  fi
  local dest="${2:-${DOWNLOAD_DIR}}"
  mkdir -p "${dest}"
  openshell sandbox download "${SANDBOX_NAME}" "${source}" "${dest}"
}

cmd_status() {
  echo "Gateway: ${OPENSHELL_GATEWAY_ENDPOINT}"
  openshell status || true
  echo
  echo "Sandbox ${SANDBOX_NAME}:"
  openshell sandbox get "${SANDBOX_NAME}" 2>&1 || echo "  not created yet; \`opencode\` creates it"
  echo
  echo "Policy file: ${POLICY}"
}

cmd_policy() {
  wait_for_gateway
  ensure_policy
  openshell policy set "${SANDBOX_NAME}" --policy "${POLICY}" --wait
  echo "Network rules are live. Filesystem and process changes need \`opencode-sandbox reset --yes\`."
}

cmd_logs() {
  wait_for_gateway
  openshell logs "${SANDBOX_NAME}" --source sandbox -n "${1:-100}"
}

cmd_rules() {
  wait_for_gateway
  openshell rule get "${SANDBOX_NAME}" --status pending
}

cmd_decide() {
  local decision="$1"
  shift
  (( $# == 1 )) || die "usage: opencode-sandbox ${decision} <chunk-id> (see opencode-sandbox rules)"
  wait_for_gateway
  openshell rule "${decision}" "${SANDBOX_NAME}" --chunk-id "$1"
}

cmd_reset() {
  [[ "${1:-}" == "--yes" ]] ||
    die "reset deletes the sandbox and every file in it. Download what you need, then run: opencode-sandbox reset --yes"
  wait_for_gateway
  openshell sandbox delete "${SANDBOX_NAME}" > /dev/null 2>&1 || true
  ensure_sandbox
  echo "Created a new sandbox ${SANDBOX_NAME}."
}

# ---- selftest

PASSED=0
FAILED=0

check() {
  local label="$1" expected="$2" output
  shift 2
  output="$(openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" --no-tty \
    --timeout 180 -- bash -c "$*" 2>&1 || true)"
  if [[ "${output}" == *"${expected}"* ]]; then
    PASSED=$((PASSED + 1))
    printf 'PASS  %s\n' "${label}"
  else
    FAILED=$((FAILED + 1))
    printf 'FAIL  %s\n      expected "%s", got: %s\n' "${label}" "${expected}" "$(tail -c 400 <<< "${output}")"
  fi
}

cmd_selftest() {
  ensure_sandbox
  local model
  model="$(OPENCODE_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/resolve-model.sh")"
  local ollama="http://host.openshell.internal:11434"
  local chat_body
  chat_body="$(jq -nc --arg model "${model}" \
    '{model: $model, max_tokens: 16, messages: [{role: "user", content: "Reply with one word: ready"}]}')"
  echo "Sandbox ${SANDBOX_NAME}, model ${model}"

  # shellcheck disable=SC2016 # These commands are expanded inside the sandbox.
  check "runs as a non-root user" "uid=1500" 'echo "uid=$(id -u)"'
  check "system folders are read-only" "read-only" \
    'touch /usr/selftest 2> /dev/null && echo writable || echo read-only'
  check "no cloud credentials in the environment" "none" \
    'env | grep -qiE "ya29\.|GOOGLE_APPLICATION_CREDENTIALS|AWS_SECRET|CLOUDSDK" && echo found || echo none'
  check "no gcloud or wb CLI" "absent" \
    'command -v gcloud wb bq gsutil > /dev/null && echo present || echo absent'
  check "public internet is blocked" "blocked" \
    'curl -sS -m 10 -o /dev/null https://example.com 2> /dev/null && echo reachable || echo blocked'
  check "cloud metadata server is blocked" "blocked" \
    'curl -sS -m 5 -o /dev/null -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/ 2> /dev/null && echo reachable || echo blocked'
  check "code-server on the VM is blocked" "blocked" \
    'curl -sS -m 5 -o /dev/null http://host.openshell.internal:8443/ 2> /dev/null && echo reachable || echo blocked'
  check "OpenShell gateway is blocked" "blocked" \
    'curl -sS -m 5 -o /dev/null http://host.openshell.internal:8090/ 2> /dev/null && echo reachable || echo blocked'
  check "Ollama model downloads (/api/pull) are blocked" "blocked" \
    "code=\$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -X POST ${ollama}/api/pull -d '{\"model\":\"x\"}' 2> /dev/null); [ \"\$code\" = 200 ] && echo allowed || echo \"blocked (HTTP \$code)\""
  check "other Ollama endpoints (/api/tags) are blocked" "blocked" \
    "code=\$(curl -sS -m 10 -o /dev/null -w '%{http_code}' ${ollama}/api/tags 2> /dev/null); [ \"\$code\" = 200 ] && echo allowed || echo \"blocked (HTTP \$code)\""
  check "local model chat endpoint answers" '"choices"' \
    "curl -sS -m 170 ${ollama}/v1/chat/completions -H 'Content-Type: application/json' -d '${chat_body}'"

  # Small models sometimes answer with reasoning only, so check that OpenCode
  # completed a model call rather than what the model said.
  local opencode_output
  opencode_output="$(exec_opencode --no-tty run --format json "Reply with exactly one word: ready" 2>&1 || true)"
  if grep -q '"type":"step_finish".*"reason":"stop"' <<< "${opencode_output}"; then
    PASSED=$((PASSED + 1))
    echo "PASS  OpenCode in the sandbox gets an answer from the local model"
  else
    FAILED=$((FAILED + 1))
    printf 'FAIL  OpenCode in the sandbox gets an answer from the local model\n      got: %s\n' \
      "$(tail -c 400 <<< "${opencode_output}")"
  fi

  sleep 2
  if openshell logs "${SANDBOX_NAME}" --source sandbox --since 10m -n 1000 2> /dev/null |
    grep -q 'DENIED.*example\.com'; then
    PASSED=$((PASSED + 1))
    echo "PASS  OpenShell logged the blocked internet request"
  else
    FAILED=$((FAILED + 1))
    echo "FAIL  OpenShell logged the blocked internet request (see opencode-sandbox logs)"
  fi

  echo
  echo "${PASSED} passed, ${FAILED} failed"
  (( FAILED == 0 ))
}

main() {
  command -v openshell > /dev/null 2>&1 || die "the openshell CLI is not installed"
  local command="${1:-run}"
  if (( $# > 0 )); then
    shift
  fi
  case "${command}" in
    run) cmd_run "$@" ;;
    shell) cmd_shell ;;
    upload) cmd_upload "$@" ;;
    download) cmd_download "$@" ;;
    status) cmd_status ;;
    policy) cmd_policy ;;
    logs) cmd_logs "$@" ;;
    rules) cmd_rules ;;
    approve|reject) cmd_decide "${command}" "$@" ;;
    reset) cmd_reset "$@" ;;
    selftest) cmd_selftest ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 1 ;;
  esac
}

main "$@"
