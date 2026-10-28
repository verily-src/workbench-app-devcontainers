#!/bin/bash

# Runs the agent harness (OpenCode by default) in an NVIDIA OpenShell sandbox
# and manages that sandbox.
#
# The sandbox holds no credentials and can reach only what the policy allows: by
# default, Ollama's chat API for the local Nemotron models. Every connection it
# makes is checked and logged by OpenShell. The harness, the program that runs in
# the sandbox, is defined in /config/openshell/harness.yaml. See README.md,
# "Sandboxed agent" and "Harness".

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
readonly USER_HOME_DIR="${OPENCODE_HOME:-/config}"
# The harness (harness.yaml) decides the sandbox's name, image, program and
# working directory; load_harness sets these.
SANDBOX_NAME=""
SANDBOX_IMAGE=""
SANDBOX_WORKDIR=""
readonly DEFAULT_POLICY="${SCRIPT_DIR}/openshell/policy.yaml"
readonly POLICY="${USER_HOME_DIR}/openshell/policy.yaml"
# Data access (README, "Data access"): rules generated from data-access.yaml are
# added to policy.yaml in policy.effective.yaml, the file the sandbox runs with.
readonly DEFAULT_DATA_ACCESS="${SCRIPT_DIR}/openshell/data-access.yaml"
readonly HARNESS_DIR="${SCRIPT_DIR}/openshell/harnesses"
readonly DEFAULT_HARNESS="opencode"
# The active harness. AGENT_HARNESS points one run at another file.
readonly HARNESS="${AGENT_HARNESS:-${USER_HOME_DIR}/openshell/harness.yaml}"
readonly DATA_ACCESS="${USER_HOME_DIR}/openshell/data-access.yaml"
readonly EFFECTIVE_POLICY="${USER_HOME_DIR}/openshell/policy.effective.yaml"
# Data collection policies (README, "Data collection policies"): the openshell-*
# properties of the collections this workspace imported from, read from Workbench
# by collection-policy.py, and what render-policy.py decided from them.
readonly COLLECTIONS="${USER_HOME_DIR}/openshell/collections.json"
readonly POLICY_SUMMARY="${USER_HOME_DIR}/openshell/policy.summary.json"
readonly GOOGLE_PROFILE="${SCRIPT_DIR}/openshell/google-cloud-profile.yaml"
readonly DOWNLOAD_DIR="${USER_HOME_DIR}/sandbox-downloads"
# The sandbox reaches the app's Ollama through the VM's loopback.
readonly SANDBOX_OLLAMA_URL="http://host.openshell.internal:11434/v1"
readonly CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
# Written every minute by the port-guard container (port-guard.sh).
readonly PORT_GUARD_STATUS="/opt/port-guard/port-guard"

# Audit log (README, "Audit log"). Snapshots of the sandbox's decisions are kept
# here, and survive `reset`. The gateway's own JSONL is mounted read-only.
readonly AUDIT_DIR="${USER_HOME_DIR}/openshell/audit"
readonly GATEWAY_AUDIT_DIR="${AGENT_GATEWAY_AUDIT_DIR:-/var/lib/openshell-audit}"

export OPENSHELL_GATEWAY_ENDPOINT="${OPENSHELL_GATEWAY_ENDPOINT:-http://openshell-gateway:8080}"
export OPENSHELL_TELEMETRY_ENABLED=false
export NO_COLOR=1

usage() {
  cat <<EOF
Usage: agent-sandbox <command> [arguments]     (also installed as opencode-sandbox)

  run [args]               Start the harness in the sandbox (\`opencode\` does this for OpenCode)
  harness [name]           List the shipped harnesses, or make one the active harness
  shell                    Open a shell in the sandbox
  upload <path> [dest]     Copy files into the sandbox (default: ${SANDBOX_WORKDIR})
  download <path> [dest]   Copy files out of the sandbox (default: ${DOWNLOAD_DIR})
  status                   Show the gateway, the sandbox and the policy file
  policy                   Apply ${POLICY}, ${DATA_ACCESS}, the harness and the data collections' policies to the running sandbox
  policy explain           Show what the data collections' policies decided
  logs [count]             Show the sandbox's recent network decisions (default 100)
  rules                    List rules OpenShell drafted from blocked connections
  approve <chunk-id>       Approve a drafted rule for this sandbox (unless a data collection forbids it)
  reject <chunk-id>        Reject a drafted rule
  audit save               Save the sandbox's recent decisions and the gateway's audit log to ${AUDIT_DIR}
  audit export <gs://dest> Save, then copy the saved files to a bucket
  reset --yes              Save the audit log, delete the harness's sandbox and its files, then create a new one
  selftest                 Check the sandbox's isolation and model access
EOF
}

die() {
  echo "agent-sandbox: $*" >&2
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

# Reads the active harness (copying the default into place on first use) and
# sets the sandbox's name, image and working directory from it.
HARNESS_JSON=""
load_harness() {
  if [[ ! -s "${HARNESS}" ]]; then
    mkdir -p "$(dirname "${HARNESS}")"
    cp "${HARNESS_DIR}/${DEFAULT_HARNESS}.yaml" "${HARNESS}"
    echo "Wrote the default harness (${DEFAULT_HARNESS}) to ${HARNESS}" >&2
  fi
  HARNESS_JSON="$(python3 "${SCRIPT_DIR}/openshell/harness.py" "${HARNESS}")" ||
    die "invalid harness ${HARNESS}"
  SANDBOX_NAME="${AGENT_SANDBOX_NAME:-${OPENCODE_SANDBOX_NAME:-agent-$(jq -r .name <<< "${HARNESS_JSON}")}}"
  SANDBOX_IMAGE="${AGENT_SANDBOX_IMAGE:-${OPENCODE_SANDBOX_IMAGE:-$(jq -r .image <<< "${HARNESS_JSON}")}}"
  SANDBOX_WORKDIR="$(jq -r .workdir <<< "${HARNESS_JSON}")"
}

cmd_harness() {
  if (( $# == 0 )); then
    local file name
    echo "Shipped harnesses (active: $(jq -r .name <<< "${HARNESS_JSON}")):"
    for file in "${HARNESS_DIR}"/*.yaml; do
      name="$(basename "${file}" .yaml)"
      printf '  %s\n' "${name}"
    done
    echo "Switch with: agent-sandbox harness <name>, then agent-sandbox reset --yes"
    return 0
  fi
  (( $# == 1 )) && [[ "$1" =~ ^[a-z0-9-]+$ && -f "${HARNESS_DIR}/$1.yaml" ]] ||
    die "no shipped harness named '${1:-}'. Run: agent-sandbox harness"
  cp "${HARNESS_DIR}/$1.yaml" "${HARNESS}"
  echo "Active harness is now $1 (${HARNESS}). Each harness has its own sandbox: \`agent-sandbox reset --yes\` creates it."
}

# Writes the effective policy: policy.yaml, the harness's binaries, and the
# data-access rules if on.
ensure_policy() {
  mkdir -p "$(dirname "${POLICY}")"
  if [[ ! -s "${POLICY}" ]]; then
    cp "${DEFAULT_POLICY}" "${POLICY}"
    echo "Wrote the default sandbox policy to ${POLICY}" >&2
  fi
  if [[ ! -s "${DATA_ACCESS}" ]]; then
    cp "${DEFAULT_DATA_ACCESS}" "${DATA_ACCESS}"
    echo "Wrote the default data-access settings to ${DATA_ACCESS}" >&2
  fi
  # The collections' policies are read from Workbench on every render, so a change a
  # collection's owners make applies the next time the sandbox starts or `policy` runs.
  # If Workbench can't be read, the file says so and the render fails closed.
  python3 "${SCRIPT_DIR}/openshell/collection-policy.py" "${COLLECTIONS}" ||
    die "could not read the data collections' policies (${SCRIPT_DIR}/openshell/collection-policy.py)"
  local rendered
  rendered="$(mktemp)"
  # data-access.yaml leaves project_id blank to mean this workspace's project.
  GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2> /dev/null || true)}" \
    python3 "${SCRIPT_DIR}/openshell/render-policy.py" "${POLICY}" "${DATA_ACCESS}" "${HARNESS}" "${COLLECTIONS}" \
    --summary "${POLICY_SUMMARY}" > "${rendered}" ||
    { rm -f "${rendered}"; die "could not build the sandbox policy from ${POLICY}, ${DATA_ACCESS}, ${HARNESS} and ${COLLECTIONS}"; }
  mv "${rendered}" "${EFFECTIVE_POLICY}"
}

# What the data collections' policies decided, from the last render.
policy_explain() {
  [[ -s "${POLICY_SUMMARY}" ]] || { echo "No policy rendered yet; run \`agent-sandbox policy\`."; return 0; }
  jq -r '
    "Data collections: " + (if (.collections | length) == 0 then "none imported" else
      (.collections | map("\(.id) \(.versions | join("/")) (agent access \(.agent_access); \(.resources | length) resources)") | join("; ")) end),
    "Internet beyond the model and the data: " + (if .internet == null then "as policy.yaml allows"
      elif (.internet | length) == 0 then "none" else ("only " + (.internet | join(", "))) end),
    "Rule approvals: " + (if .rule_approvals then "allowed" else "forbidden by a data collection" end),
    (if (.notes | length) > 0 then "Decisions:\n" + (.notes | map("  - " + .) | join("\n")) else empty end)
  ' "${POLICY_SUMMARY}"
}

# True unless a data collection set openshell-rule-approvals=false (or Workbench
# could not be read, which counts as the strictest setting).
approvals_allowed() {
  [[ -s "${POLICY_SUMMARY}" ]] && [[ "$(jq -r .rule_approvals "${POLICY_SUMMARY}")" == "true" ]]
}

data_access_enabled() {
  grep -qE '^enabled:[[:space:]]*true' "${DATA_ACCESS}" 2> /dev/null
}

data_access_provider() {
  sed -n 's/^provider:[[:space:]]*\([A-Za-z0-9._-]*\).*/\1/p' "${DATA_ACCESS}" | head -n 1
}

# Creates the google-cloud provider from this app's Application Default
# Credentials. The refresh token stays at the gateway; the sandbox only ever
# sees a placeholder.
ensure_provider() {
  local provider
  provider="$(data_access_provider)"
  provider="${provider:-wb-gcp}"
  if openshell provider get "${provider}" > /dev/null 2>&1; then
    return 0
  fi
  if ! openshell provider list-profiles 2> /dev/null | grep -q '^google-cloud '; then
    openshell profile import --file "${GOOGLE_PROFILE}" --global > /dev/null
  fi
  local project="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2> /dev/null || true)}"
  [[ -n "${project}" ]] || die "no Google Cloud project: set project_id in ${DATA_ACCESS}"
  echo "Creating the ${provider} credential provider from this app's Application Default Credentials..." >&2
  openshell provider create --name "${provider}" --type google-cloud --from-gcloud-adc \
    --config "project_id=${project}" --config region=global > /dev/null
}

sandbox_phase() {
  openshell sandbox get "${SANDBOX_NAME}" -o json 2> /dev/null |
    jq -r '[.. | objects | .phase? | strings] | first // "unknown"' 2> /dev/null || true
}

ensure_sandbox() {
  wait_for_gateway
  ensure_policy
  # OpenShell's full JSON audit records for every sandbox. Best effort.
  openshell settings set --global --key ocsf_json_enabled --value true > /dev/null 2>&1 || true
  if ! openshell sandbox get "${SANDBOX_NAME}" > /dev/null 2>&1; then
    echo "Creating sandbox ${SANDBOX_NAME} from ${SANDBOX_IMAGE} with ${EFFECTIVE_POLICY}..." >&2
    # No trailing command: OpenShell keeps a login shell running, and the
    # harness starts with `sandbox exec`. Proposals for blocked connections always wait
    # for a person (--approval-mode manual).
    local provider_args=()
    if data_access_enabled; then
      ensure_provider
      provider_args=(--provider "$(data_access_provider)")
    fi
    openshell sandbox create --name "${SANDBOX_NAME}" --from "${SANDBOX_IMAGE}" \
      --policy "${EFFECTIVE_POLICY}" --no-auto-providers --no-tty --detach \
      --approval-mode manual --label app=opencode-nemotron ${provider_args[@]+"${provider_args[@]}"} > /dev/null
    return 0
  fi
  case "$(sandbox_phase)" in
    Stopped|stopped|STOPPED)
      echo "Starting stopped sandbox ${SANDBOX_NAME}..." >&2
      openshell sandbox start "${SANDBOX_NAME}" > /dev/null
      ;;
  esac
}

# What every harness gets: HOME, and the image's venv (with the Google client
# libraries) ahead of the system Python. The harness's own env is added after.
readonly BASE_ENV=(
  HOME=/sandbox
  PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
)

# The model the harness must use, running the picker first if none is chosen.
agent_model() {
  local model
  model="$(OPENCODE_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/resolve-model.sh")"
  if [[ "${model}" == "prompt" ]]; then
    "${SCRIPT_DIR}/opencode-model.sh" >&2
    model="$(OPENCODE_HOME="${USER_HOME_DIR}" "${SCRIPT_DIR}/resolve-model.sh")"
  fi
  printf '%s\n' "${model}"
}

# Runs the harness in the sandbox. Every harness gets OLLAMA_BASE_URL and
# AGENT_MODEL. If it has a config hook, the hook's output is passed in the
# variable the harness names, base64-encoded so it survives the remote command
# line unchanged.
exec_harness() {
  local tty_flag="$1"
  shift
  local model hook config_env config="" env_args=()
  model="$(agent_model)"
  hook="$(jq -r '.config.hook // empty' <<< "${HARNESS_JSON}")"
  config_env="$(jq -r '.config.env // empty' <<< "${HARNESS_JSON}")"
  # A relative hook path is relative to the framework directory.
  if [[ -n "${hook}" && "${hook}" != /* ]]; then
    hook="${SCRIPT_DIR}/${hook}"
  fi
  if [[ -n "${hook}" ]]; then
    config="$(AGENT_MODEL="${model}" OLLAMA_BASE_URL="${SANDBOX_OLLAMA_URL}" AGENT_CONTEXT_LENGTH="${CONTEXT_LENGTH}" \
      OPENCODE_HOME="${USER_HOME_DIR}" "${hook}" | base64 -w0)" ||
      die "the harness config hook ${hook} failed"
  fi
  mapfile -t env_args < <(jq -r '.env | to_entries[] | "\(.key)=\(.value)"' <<< "${HARNESS_JSON}")
  local command=()
  mapfile -t command < <(jq -r '.command[]' <<< "${HARNESS_JSON}")
  # shellcheck disable=SC2016 # Expanded inside the sandbox, not here.
  openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" "${tty_flag}" -- \
    env "${BASE_ENV[@]}" ${env_args[@]+"${env_args[@]}"} "OLLAMA_BASE_URL=${SANDBOX_OLLAMA_URL}" "AGENT_MODEL=${model}" \
    bash -c 'if [[ -n "$1" ]]; then export "$2=$(printf %s "$1" | base64 -d)"; fi; shift 2; exec "$@"' \
    agent-sandbox "${config}" "${config_env}" "${command[@]}" "$@"
}

cmd_run() {
  ensure_sandbox
  exec_harness --tty "$@"
}

cmd_shell() {
  ensure_sandbox
  local env_args=()
  mapfile -t env_args < <(jq -r '.env | to_entries[] | "\(.key)=\(.value)"' <<< "${HARNESS_JSON}")
  exec openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" --tty -- \
    env "${BASE_ENV[@]}" ${env_args[@]+"${env_args[@]}"} bash -l
}

cmd_upload() {
  (( $# >= 1 && $# <= 2 )) || die "usage: agent-sandbox upload <path> [dest]"
  ensure_sandbox
  openshell sandbox upload "${SANDBOX_NAME}" "$1" "${2:-${SANDBOX_WORKDIR}}"
}

cmd_download() {
  (( $# >= 1 && $# <= 2 )) || die "usage: agent-sandbox download <path> [dest]"
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
  policy_explain
  echo
  echo "port-guard (${PORT_GUARD_STATUS}):"
  cat "${PORT_GUARD_STATUS}" 2> /dev/null || echo "  no status: the port-guard container has not written one"
}

# The VM's internal IP, for checking from another VM that code-server is closed.
vm_internal_ip() {
  curl -fsS -m 3 -H 'Metadata-Flavor: Google' \
    http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip 2> /dev/null ||
    echo "<this VM's internal IP>"
}

# port-guard's status must be recent and report the rule in place.
check_port_guard() {
  local label="code-server is closed to other VMs (port-guard rule in place)"
  local updated age
  updated="$(sed -n 's/^time=//p' "${PORT_GUARD_STATUS}" 2> /dev/null || true)"
  age=$(( $(date +%s) - ${updated:-0} ))
  if grep -q '^state=ok' "${PORT_GUARD_STATUS}" 2> /dev/null && (( age < 300 )); then
    PASSED=$((PASSED + 1))
    printf 'PASS  %s\n' "${label}"
  else
    FAILED=$((FAILED + 1))
    printf 'FAIL  %s\n      status: %s\n' "${label}" \
      "$(head -c 600 "${PORT_GUARD_STATUS}" 2> /dev/null || echo "missing; port-guard has not run")"
  fi
}

# The gateway's JSONL must be written and parse as OCSF. It records gateway
# events (sandbox lifecycle, policy changes), not the sandbox's own decisions.
check_gateway_audit() {
  local label="gateway audit log is written as OCSF JSONL"
  if [[ ! -d "${GATEWAY_AUDIT_DIR}" ]]; then
    echo "SKIP  ${label} (${GATEWAY_AUDIT_DIR} is not mounted)"
    return 0
  fi
  if gateway_audit 2> /dev/null | head -n 1 | jq -e '.class_uid' > /dev/null 2>&1; then
    PASSED=$((PASSED + 1))
    printf 'PASS  %s\n' "${label}"
  else
    FAILED=$((FAILED + 1))
    printf 'FAIL  %s\n      nothing parseable in %s; is [openshell.gateway.ocsf_log] set and the gateway restarted?\n' \
      "${label}" "${GATEWAY_AUDIT_DIR}"
  fi
}

cmd_policy() {
  if [[ "${1:-}" == "explain" ]]; then
    policy_explain
    return 0
  fi
  (( $# == 0 )) || die "usage: agent-sandbox policy [explain]"
  wait_for_gateway
  ensure_policy
  policy_explain >&2
  # A provider attaches only when a sandbox is created; its project variable
  # shows whether this sandbox has it.
  if data_access_enabled && openshell sandbox get "${SANDBOX_NAME}" > /dev/null 2>&1 &&
    ! openshell sandbox exec "${SANDBOX_NAME}" --no-tty -- sh -c 'test -n "${GCP_PROJECT_ID:-}"' > /dev/null 2>&1; then
    echo "Note: this sandbox was created before data access was on, so it has no Google credential provider." >&2
    echo "      Run \`opencode-sandbox reset --yes\` once to attach it." >&2
  fi
  openshell policy set "${SANDBOX_NAME}" --policy "${EFFECTIVE_POLICY}" --wait
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
  (( $# == 1 )) || die "usage: agent-sandbox ${decision} <chunk-id> (see agent-sandbox rules)"
  wait_for_gateway
  if [[ "${decision}" == approve ]]; then
    # An approved rule widens the sandbox's policy outside the render; a data collection
    # can forbid that. Re-render first so the decision is current.
    ensure_policy
    approvals_allowed || die "a data collection in this workspace forbids approving drafted rules (agent-sandbox policy explain). Add the destination to ${POLICY} instead, if the collections allow it."
  fi
  openshell rule "${decision}" "${SANDBOX_NAME}" --chunk-id "$1"
}

# The gateway's audit files, oldest first. They are owner-only, so read with sudo.
gateway_audit() {
  local files=()
  [[ -d "${GATEWAY_AUDIT_DIR}" ]] || return 1
  shopt -s nullglob
  files=("${GATEWAY_AUDIT_DIR}"/gateway-ocsf.jsonl.* "${GATEWAY_AUDIT_DIR}"/gateway-ocsf.jsonl)
  shopt -u nullglob
  (( ${#files[@]} > 0 )) || return 1
  cat "${files[@]}" 2> /dev/null || sudo -n cat "${files[@]}"
}

# Saves what OpenShell can show now: the sandbox's last 2,000 log lines (the
# gateway keeps no more, in memory, and drops them when the sandbox is deleted)
# and the gateway's JSONL. Prints the files it wrote.
audit_save() {
  local stamp file
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${AUDIT_DIR}"
  file="${AUDIT_DIR}/${SANDBOX_NAME}-${stamp}.log"
  if openshell logs "${SANDBOX_NAME}" --source all -n 2000 > "${file}" 2> /dev/null && [[ -s "${file}" ]]; then
    echo "${file}"
  else
    rm -f "${file}"
  fi
  file="${AUDIT_DIR}/gateway-ocsf-${stamp}.jsonl"
  if gateway_audit > "${file}" 2> /dev/null && [[ -s "${file}" ]]; then
    echo "${file}"
  else
    rm -f "${file}"
  fi
}

cmd_audit() {
  wait_for_gateway
  local saved
  case "${1:-}" in
    save)
      saved="$(audit_save)"
      [[ -n "${saved}" ]] || die "nothing to save: no sandbox log and no gateway audit file"
      echo "${saved}"
      ;;
    export)
      [[ "${2:-}" =~ ^gs://[a-z0-9][a-z0-9._-]*(/.*)?$ ]] || die "usage: agent-sandbox audit export gs://<bucket>[/<folder>]"
      saved="$(audit_save)"
      [[ -n "${saved}" ]] || die "nothing to export: no sandbox log and no gateway audit file"
      local files=()
      mapfile -t files <<< "${saved}"
      gcloud storage cp "${files[@]}" "${2%/}/"
      ;;
    *) die "usage: agent-sandbox audit save | audit export gs://<bucket>[/<folder>]" ;;
  esac
}

cmd_reset() {
  [[ "${1:-}" == "--yes" ]] ||
    die "reset deletes the sandbox and every file in it. Download what you need, then run: agent-sandbox reset --yes"
  wait_for_gateway
  # Deleting the sandbox drops its log from the gateway.
  local saved
  saved="$(audit_save 2> /dev/null || true)"
  if [[ -n "${saved}" ]]; then
    echo "Saved the audit log before deleting the sandbox:" >&2
    echo "${saved}" >&2
  fi
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

# Data-access checks: only when data-access.yaml turns it on. Each request is
# sent from inside the sandbox by data-probe.py, which prints "denied" when
# OpenShell blocks it.
selftest_data_access() {
  local probe="/opt/venv/bin/python /opt/opencode-sandbox/data-probe.py"
  local config project dataset bucket bq
  config="$(python3 -c '
import sys, yaml
c = yaml.safe_load(open(sys.argv[1])) or {}
b = c.get("bigquery") or {}
d = (b.get("datasets") or [{}])[0]
s = (c.get("storage") or {}).get("buckets") or [""]
print(c.get("project_id") or "", d.get("project", ""), d.get("dataset", ""), s[0])' "${DATA_ACCESS}")"
  read -r project _ dataset bucket <<< "${config}"
  project="${project:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2> /dev/null)}}"
  bq="https://bigquery.googleapis.com/bigquery/v2/projects"

  # shellcheck disable=SC2016 # Expanded inside the sandbox.
  check "Google token in the sandbox is a placeholder" "placeholder" \
    'case "${GCP_ADC_ACCESS_TOKEN:-}" in openshell:resolve:*) echo placeholder;; "") echo missing;; *) echo REAL-TOKEN;; esac'
  check "BigQuery query runs with the Python client" "rows=1" \
    "${probe} --query 'SELECT 1' ${project}"
  if [[ -n "${dataset}" ]]; then
    check "approved dataset can be looked up" "HTTP 200" "${probe} GET ${bq}/${project}/datasets/${dataset}"
    check "tables can't be deleted through the API" "denied" \
      "${probe} DELETE ${bq}/${project}/datasets/${dataset}/tables/selftest-missing"
    check "rows can't be streamed into tables (insertAll)" "denied" \
      "${probe} POST ${bq}/${project}/datasets/${dataset}/tables/selftest-missing/insertAll '{\"rows\":[]}'"
  fi
  check "datasets can't be browsed" "denied" "${probe} GET ${bq}/${project}/datasets"
  check "queries can't be billed to another project" "denied" \
    "${probe} POST ${bq}/bigquery-public-data/queries '{\"query\":\"SELECT 1\",\"useLegacySql\":false}'"
  check "curl can't reach BigQuery (only the Python client)" "blocked" \
    "curl -sS -m 10 -o /dev/null ${bq}/${project}/datasets 2> /dev/null && echo reachable || echo blocked"
  if [[ -n "${bucket}" ]]; then
    check "approved bucket can be read" "HTTP 200" \
      "${probe} GET https://storage.googleapis.com/storage/v1/b/${bucket}/o"
    check "approved bucket can't be written" "denied" \
      "${probe} POST 'https://storage.googleapis.com/upload/storage/v1/b/${bucket}/o?uploadType=media&name=selftest.txt' x"
  fi
  check "other buckets can't be read" "denied" \
    "${probe} GET https://storage.googleapis.com/storage/v1/b/selftest-not-approved-${project}/o"
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

  # Small models sometimes answer with reasoning only, so the harness check
  # looks for a completed model call rather than what the model said.
  local harness_name harness_expect harness_output
  harness_name="$(jq -r .name <<< "${HARNESS_JSON}")"
  harness_expect="$(jq -r '.selftest.expect // empty' <<< "${HARNESS_JSON}")"
  if [[ -z "${harness_expect}" ]]; then
    echo "SKIP  harness ${harness_name} defines no selftest"
  else
    local harness_args=()
    mapfile -t harness_args < <(jq -r '.selftest.args[]' <<< "${HARNESS_JSON}")
    harness_output="$(exec_harness --no-tty ${harness_args[@]+"${harness_args[@]}"} 2>&1 || true)"
    if grep -Eq "${harness_expect}" <<< "${harness_output}"; then
      PASSED=$((PASSED + 1))
      echo "PASS  harness ${harness_name} in the sandbox gets an answer from the local model"
    else
      FAILED=$((FAILED + 1))
      printf 'FAIL  harness %s in the sandbox gets an answer from the local model\n      got: %s\n' \
        "${harness_name}" "$(tail -c 400 <<< "${harness_output}")"
    fi
  fi

  # Read the whole log before searching it: with pipefail, `grep -q` closing the
  # pipe early would make the pipeline fail even when it matches.
  sleep 2
  local log
  log="$(openshell logs "${SANDBOX_NAME}" --source sandbox --since 30m -n 2000 2> /dev/null || true)"
  if grep -q 'DENIED.*example\.com' <<< "${log}"; then
    PASSED=$((PASSED + 1))
    echo "PASS  OpenShell logged the blocked internet request"
  else
    FAILED=$((FAILED + 1))
    echo "FAIL  OpenShell logged the blocked internet request (see agent-sandbox logs)"
  fi

  if data_access_enabled; then
    selftest_data_access
  fi

  # The collections' policies were read, not assumed: an unreadable Workbench renders the
  # strictest policy, which keeps the sandbox safe but is not what the collections asked for.
  if [[ -s "${COLLECTIONS}" ]] && [[ "$(jq -r .unavailable "${COLLECTIONS}")" == "false" ]]; then
    PASSED=$((PASSED + 1))
    printf 'PASS  data collection policies read from Workbench (%s collections)\n' \
      "$(jq -r '.collections | length' "${COLLECTIONS}")"
  else
    FAILED=$((FAILED + 1))
    printf 'FAIL  data collection policies read from Workbench\n      %s\n' \
      "$(jq -r '.errors | join("; ")' "${COLLECTIONS}" 2> /dev/null || echo "no ${COLLECTIONS}")"
  fi

  check_gateway_audit
  check_port_guard

  echo
  echo "${PASSED} passed, ${FAILED} failed"
  echo
  echo "This app can't test its own network card. To confirm code-server is closed, run from another"
  echo "app in the workspace (it should time out, not return HTTP 302):"
  printf '  curl -m 5 -o /dev/null -w "%%{http_code}\\n" http://%s:8443/\n' "$(vm_internal_ip)"
  (( FAILED == 0 ))
}

main() {
  command -v openshell > /dev/null 2>&1 || die "the openshell CLI is not installed"
  local command="${1:-run}"
  if (( $# > 0 )); then
    shift
  fi
  case "${command}" in
    -h|--help|help) usage; return 0 ;;
  esac
  load_harness
  case "${command}" in
    harness) cmd_harness "$@" ;;
    run) cmd_run "$@" ;;
    shell) cmd_shell ;;
    upload) cmd_upload "$@" ;;
    download) cmd_download "$@" ;;
    status) cmd_status ;;
    policy) cmd_policy "$@" ;;
    logs) cmd_logs "$@" ;;
    rules) cmd_rules ;;
    approve|reject) cmd_decide "${command}" "$@" ;;
    audit) cmd_audit "$@" ;;
    reset) cmd_reset "$@" ;;
    selftest) cmd_selftest ;;
    *) usage >&2; exit 1 ;;
  esac
}

main "$@"
