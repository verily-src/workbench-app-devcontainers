#!/bin/bash

# Runs an agent harness in an NVIDIA OpenShell sandbox and manages that sandbox (README.md).
#
# Environment this script reads (the app's compose file sets it):
#   APP_USER_HOME         the app user's home, where state is kept (default /config)
#   AGENT_BROKER          in the app: the sandbox-broker to run every command on
#   AGENT_MODEL_URL       where the sandbox reaches the model's OpenAI-compatible API
#   AGENT_MODEL           the model to serve the harness, or AGENT_MODEL_COMMAND to print it
#   AGENT_CONTEXT_LENGTH  the model's context length, for the harness
#   AGENT_MCP_URL         where the sandbox reaches the Workbench MCP server (optional)
#   AGENT_SANDBOX_CONFIG  a directory of policy.yaml and ai-policy.yaml to use instead of
#                         the feature's config/ (optional)

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
readonly SCRIPT_DIR
readonly USER_HOME_DIR="${APP_USER_HOME:-/config}"

# In the app, every command runs on the sandbox-broker (README, "Admin-locked mode").
if [[ -n "${AGENT_BROKER:-}" ]]; then
  exec "${SCRIPT_DIR}/broker-client.sh" "$@"
fi

# The policy files are the image's, or the folder the app names in AGENT_SANDBOX_CONFIG.
readonly CONFIG_DIR="${AGENT_SANDBOX_CONFIG:-${SCRIPT_DIR}/config}"
readonly POLICY="${CONFIG_DIR}/policy.yaml"
readonly AI_POLICY_FILE="${CONFIG_DIR}/ai-policy.yaml"
readonly GOOGLE_PROFILE="${CONFIG_DIR}/google-cloud-profile.yaml"
readonly TOOL_GROUPS="${SCRIPT_DIR}/tool-groups.yaml"
readonly AI_POLICY="${AI_POLICY_DIR:-/opt/ai-policy}"
# load_harness sets these from the harness file named in harnesses/default.
SANDBOX_NAME=""
SANDBOX_IMAGE=""
SANDBOX_WORKDIR=""
readonly HARNESS_DIR="${SCRIPT_DIR}/harnesses"
harness_name=""
if [[ -f "${HARNESS_DIR}/default" ]]; then
  harness_name="$(tr -cd 'a-z0-9-' < "${HARNESS_DIR}/default")"
fi
readonly HARNESS="${HARNESS_DIR}/${harness_name}.yaml"
# Copies of the last render, for the user to read. The files a sandbox is created or updated
# from are the render's own, in RENDER_DIR (ensure_policy); after a render WORKSPACE_DATA and
# POLICY_SUMMARY name those.
readonly EFFECTIVE_POLICY_ROOT="${USER_HOME_DIR}/openshell/harnesses"
EFFECTIVE_POLICY=""
WORKSPACE_DATA="${USER_HOME_DIR}/openshell/workspace-data.json"
POLICY_SUMMARY="${USER_HOME_DIR}/openshell/policy.summary.json"
RENDER_DIR=""
RENDERED_POLICY=""
# The OpenShell credential provider the data rules bind.
readonly PROVIDER="wb-gcp"
readonly DOWNLOAD_DIR="${USER_HOME_DIR}/sandbox-downloads"
readonly SANDBOX_MODEL_URL="${AGENT_MODEL_URL:-http://host.openshell.internal:8000/v1}"
# shellcheck disable=SC2034 # selftest.sh probes the model server's other endpoints with it.
readonly SANDBOX_MODEL_HOST="${SANDBOX_MODEL_URL%/v1}"
readonly CONTEXT_LENGTH="${AGENT_CONTEXT_LENGTH:-65536}"
readonly MCP_URL="${AGENT_MCP_URL:-}"
readonly PORT_GUARD_STATUS="${AGENT_PORT_GUARD_STATUS:-/opt/port-guard/port-guard}"

# Snapshots of the sandbox's decisions; they survive `reset`.
readonly AUDIT_DIR="${USER_HOME_DIR}/openshell/audit"

export OPENSHELL_GATEWAY_ENDPOINT="${OPENSHELL_GATEWAY_ENDPOINT:-http://openshell-gateway:8080}"
export OPENSHELL_TELEMETRY_ENABLED=false
export NO_COLOR=1
# HOME here is the user's home, which the app can write: Python must not load packages from it
# (~/.local/lib/python*/site-packages), or the user's code would run where the gateway is.
export PYTHONNOUSERSITE=1

usage() {
  cat <<EOF
Usage: agent-sandbox <command> [arguments]

  run [args]               Start the harness in the sandbox
  shell                    Open a shell in the sandbox
  exec <command...>        Run one command in the sandbox (a terminal if you have one)
  upload <path> [dest]     Copy files into the sandbox (default: ${SANDBOX_WORKDIR})
  download <path> [dest]   Copy files out of the sandbox (default: ${DOWNLOAD_DIR})
  status                   Show the gateway, the sandbox, the policy files, what the policy allows and the web UI
  web                      Start the harness's web UI (its sandbox and the forward the app's front door uses)
  policy                   Render the policy again (the workspace's resources may have changed)
                           and apply it to the running sandbox
  policy explain           Show what the policy allows: the data and the Workbench tools
  logs [count]             Show the sandbox's recent network decisions (default 100)
  audit save               Save the sandbox's recent decisions and the gateway's audit log to ${AUDIT_DIR}
  audit export <gs://dest> Save, then copy the saved files to a bucket
  reset --yes              Save the audit log, delete the sandbox and its files, then create a new one
  selftest                 Check the sandbox's isolation, model access, data and tool rules
  credential refresh       Renew the sandbox's Google credential from the app's own (done for you every two minutes)
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

HARNESS_JSON=""
load_harness() {
  [[ -n "${harness_name}" ]] || die "no harness is installed: a harness feature puts its files in ${HARNESS_DIR}"
  [[ -s "${HARNESS}" ]] || die "the harness file ${HARNESS} is missing"
  HARNESS_JSON="$(python3 "${SCRIPT_DIR}/harness.py" "${HARNESS}")" ||
    die "invalid harness ${HARNESS}"
  SANDBOX_NAME="agent-$(jq -r .name <<< "${HARNESS_JSON}")"
  SANDBOX_IMAGE="$(jq -r .image <<< "${HARNESS_JSON}")"
  SANDBOX_WORKDIR="$(jq -r .workdir <<< "${HARNESS_JSON}")"
  EFFECTIVE_POLICY="${EFFECTIVE_POLICY_ROOT}/$(jq -r .name <<< "${HARNESS_JSON}")/policy.effective.yaml"
}

# Removes the render's own files; they are read-only once written (ensure_policy).
drop_render() {
  [[ -n "${RENDER_DIR}" ]] || return 0
  chmod -R u+w "${RENDER_DIR}" 2> /dev/null || true
  rm -rf "${RENDER_DIR}"
  RENDER_DIR=""
}
trap drop_render EXIT

# Renders the effective policy into a new directory of this container, read-only once written.
# The gateway is given that file, never the copy in the user's home, which the app can write
# and could swap between the render and the gateway call.
ensure_policy() {
  [[ -x "${AI_POLICY}/render-policy.py" ]] || die "the policy compiler is not installed (${AI_POLICY}; the ai-policy feature)"
  [[ -s "${AI_POLICY_FILE}" ]] || die "no AI policy: ${AI_POLICY_FILE} is missing"
  drop_render
  RENDER_DIR="$(mktemp -d)"
  RENDERED_POLICY="${RENDER_DIR}/policy.effective.yaml"
  local workspace_data="${RENDER_DIR}/workspace-data.json" summary="${RENDER_DIR}/policy.summary.json"
  local harness_json="${RENDER_DIR}/harness.json"
  # If Workbench can't be read, the file says so (or is missing) and no data rules are rendered.
  python3 "${AI_POLICY}/workspace-data.py" "${workspace_data}" ||
    echo "agent-sandbox: could not read the workspace's resources; the sandbox gets no data until it can (agent-sandbox policy)" >&2
  local workspace_args=()
  [[ -s "${workspace_data}" ]] && workspace_args=(--workspace "${workspace_data}")
  printf '%s\n' "${HARNESS_JSON}" > "${harness_json}"
  local mcp_args=()
  [[ -n "${MCP_URL}" ]] && mcp_args=(--mcp-url "${MCP_URL}")
  GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(workspace_project)}" \
    AGENT_DATA_CREDENTIAL="$(data_credential_state)" \
    python3 "${AI_POLICY}/render-policy.py" "${POLICY}" "${AI_POLICY_FILE}" --harness "${harness_json}" \
    ${workspace_args[@]+"${workspace_args[@]}"} --tools "${TOOL_GROUPS}" --provider "${PROVIDER}" \
    ${mcp_args[@]+"${mcp_args[@]}"} --summary "${summary}" > "${RENDERED_POLICY}" ||
    die "could not build the sandbox policy from ${POLICY}, ${AI_POLICY_FILE} and ${HARNESS}"
  chmod -R a-w "${RENDER_DIR}"

  # Copies for the user to read (`status`, `policy explain`); nothing reads them back as policy.
  local shown="${USER_HOME_DIR}/openshell"
  mkdir -p "${shown}" "$(dirname "${EFFECTIVE_POLICY}")"
  install -m 644 "${RENDERED_POLICY}" "${EFFECTIVE_POLICY}"
  install -m 644 "${summary}" "${shown}/policy.summary.json"
  POLICY_SUMMARY="${summary}"
  if [[ -s "${workspace_data}" ]]; then
    install -m 644 "${workspace_data}" "${shown}/workspace-data.json"
    # shellcheck disable=SC2034 # selftest.sh reads it.
    WORKSPACE_DATA="${workspace_data}"
  else
    rm -f "${shown}/workspace-data.json"
  fi
}

policy_explain() {
  [[ -s "${POLICY_SUMMARY}" ]] || { echo "No policy rendered yet; run \`agent-sandbox policy\`."; return 0; }
  jq -r '
    "Data: " + (if (.data.enabled | not) then "none"
      else ("read \(.data.datasets | length) datasets and \(.data.buckets | length) buckets of the workspace"
        + (if .data.write then "; write to the \([.data.datasets[], .data.buckets[] | select(.write)] | length) it owns" else "; read-only" end)) end),
    "Workbench tools: " + (if (.tools.enabled | not) then "none"
      else ("\(.tools.allowed | length) allowed at \(.tools.url)" + (if (.tools.denied | length) > 0 then "; denied: \(.tools.denied | join(", "))" else "" end)) end),
    (if (.notes | length) > 0 then "Decisions:\n" + (.notes | map("  - " + .) | join("\n")) else empty end)
  ' "${POLICY_SUMMARY}"
}

data_access_enabled() {
  # In a subshell at /, not the user's home: `python3 -c` imports from the current directory first.
  (cd / && python3 -c 'import sys, yaml; sys.exit(0 if ((yaml.safe_load(open(sys.argv[1])) or {}).get("data") or {}).get("read", "workspace") == "workspace" else 1)' "${AI_POLICY_FILE}" 2> /dev/null)
}

# The workspace's Google Cloud project. The broker has no gcloud, so it reads wb's context file.
workspace_project() {
  if command -v gcloud > /dev/null 2>&1; then
    gcloud config get-value project 2> /dev/null && return 0
  fi
  jq -r '.workspace.googleProjectId // empty' "${USER_HOME_DIR}/.workbench/context.json" 2> /dev/null || true
}

# The app's own Google credential: the token of the service account the VM runs as. It lasts an hour.
readonly METADATA_SERVICE_ACCOUNT="http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default"
METADATA_CREDENTIAL=""

metadata_token() {
  curl -sS -m 5 -f -H 'Metadata-Flavor: Google' "${METADATA_SERVICE_ACCOUNT}/token" 2> /dev/null |
    jq -r '.access_token // empty' 2> /dev/null || true
}

have_metadata_credential() {
  if [[ -z "${METADATA_CREDENTIAL}" ]]; then
    if curl -sS -m 5 -f -o /dev/null -H 'Metadata-Flavor: Google' "${METADATA_SERVICE_ACCOUNT}/email" 2> /dev/null; then
      METADATA_CREDENTIAL=yes
    else
      METADATA_CREDENTIAL=no
    fi
  fi
  [[ "${METADATA_CREDENTIAL}" == yes ]]
}

# Without the provider the policy is rendered without the data rules: OpenShell refuses a
# policy that binds a provider the sandbox lacks.
want_provider() {
  data_access_enabled && have_metadata_credential
}

# "missing" when data access is on but there is nothing to make the provider from.
data_credential_state() {
  if data_access_enabled && ! have_metadata_credential; then
    echo missing
  else
    echo present
  fi
}

# The token stays at the gateway. It is handed over through the environment, not the command line.
ensure_provider() {
  if openshell provider get "${PROVIDER}" > /dev/null 2>&1; then
    return 0
  fi
  if ! openshell provider list-profiles 2> /dev/null | grep -q '^google-cloud '; then
    openshell profile import --file "${GOOGLE_PROFILE}" --global > /dev/null
  fi
  local project="${GOOGLE_CLOUD_PROJECT:-$(workspace_project)}"
  [[ -n "${project}" ]] || die "no Google Cloud project: GOOGLE_CLOUD_PROJECT is not set and the Workbench context names none"
  have_metadata_credential || die "data access needs this app's Google credential, and the metadata server does not answer"
  echo "Creating the ${PROVIDER} credential provider from this app's own Google credential..." >&2
  GCP_ADC_ACCESS_TOKEN="$(metadata_token)" openshell provider create --name "${PROVIDER}" --type google-cloud \
    --credential GCP_ADC_ACCESS_TOKEN --config "project_id=${project}" --config region=global > /dev/null
}

# Pushed only when the token changed: every provider update makes the sandbox close its open
# connections, the agent's to the model included.
renew_provider() {
  data_access_enabled || return 0
  openshell provider get "${PROVIDER}" > /dev/null 2>&1 || return 0
  local token
  token="$(metadata_token)"
  [[ -n "${token}" ]] || die "the metadata server gave no token"
  local digest_file="${TMPDIR:-/tmp}/agent-sandbox-${PROVIDER}.token-digest" digest
  digest="$(printf '%s' "${token}" | sha256sum | cut -d' ' -f1)"
  if [[ -f "${digest_file}" ]] && [[ "$(cat "${digest_file}")" == "${digest}" ]]; then
    return 0
  fi
  GCP_ADC_ACCESS_TOKEN="${token}" openshell provider update "${PROVIDER}" --credential GCP_ADC_ACCESS_TOKEN > /dev/null
  printf '%s\n' "${digest}" > "${digest_file}"
}

cmd_credential() {
  [[ "${1:-}" == refresh ]] || die "usage: agent-sandbox credential refresh"
  renew_provider
}

# Tells the agent what the policy lets it reach: /sandbox/data-access.md, from the render's summary.
readonly AGENT_DATA_NOTES="/sandbox/data-access.md"

write_agent_data_notes() {
  [[ -s "${POLICY_SUMMARY}" ]] || return 0
  local notes
  notes="$(mktemp -d)"
  jq -r '
    def python: if .data.python == "/usr/bin/python3.11" then "/opt/venv/bin/python" else .data.python end;
    if (.data.enabled | not) or ((.data.datasets | length) == 0 and (.data.buckets | length) == 0) then
      "# Data access\n\nThis sandbox has no Google Cloud data access: no BigQuery dataset or Cloud Storage bucket is open to it, and there is no credential to log in with. Do not ask the user to authenticate. Work with the files in your workspace."
    else
      "# Data you can reach\n",
      "For the workspace\u0027s data, the datasets and buckets below, use this interpreter and the code shown here, not the Workbench tools: the `wb` tools are for Workbench itself (workspaces, resources, apps, workflows), and the ones that read or write data are not available here.\n",
      "Google Cloud works here without any login, through one Python interpreter: `\(python)`, which has the google-cloud-bigquery and google-cloud-storage client libraries installed. Its credential is picked up automatically (Application Default Credentials). Never run gcloud, bq or gsutil, never pip install, never ask the user to authenticate or to run anything: run your code yourself with the bash tool, with that interpreter. Example:\n",
      "    \(python) -c \"from google.cloud import bigquery; print([r for r in bigquery.Client(project=\\\"\(.data.project)\\\").query(\\\"SELECT 1\\\").result()])\"\n",
      "This is the data of the Workbench workspace you are in, and nothing else. Queries run as jobs in project `\(.data.project)`. Names are exact and case-sensitive; use them as written here, and list a dataset\u0027s tables rather than guessing.\n",
      (if (.data.datasets | length) > 0 then
        "BigQuery datasets:",
        (.data.datasets[] | "- `\(.project).\(.dataset)`" + (if .write then " (read and write: the workspace owns it)" else " (read-only)" end)), ""
      else empty end),
      (if (.data.buckets | length) > 0 then
        "Cloud Storage buckets:",
        (.data.buckets[] | "- `gs://\(.name)`" + (if .write then " (read and write: the workspace owns it)" else " (read-only)" end)), "",
        "For objects in buckets use the `wbstorage` module of that interpreter, with gs:// URLs: `wbstorage.list_objects(\"gs://bucket/folder/\")`, `wbstorage.read_text(url)` / `read_bytes(url)`, `wbstorage.write_text(url, text)` / `write_bytes(url, data)`, `wbstorage.delete(url)`. Do not use the google.cloud.storage client for objects: it fails here on any object name with a slash in it.\n"
      else empty end),
      (if .data.write then "Write results the user should keep to a bucket or dataset marked read and write; that is how they leave the sandbox. " else "Nothing can be written to Google Cloud from here. " end)
        + "Anything else is denied by the sandbox policy and logged: other datasets, buckets and projects, writes to read-only data, and any program other than that interpreter. When a request is denied, say so and stop; do not retry other ways."
    end,
    if (.tools.enabled) then
      "\n# Workbench tools\n",
      "The `wb` MCP server gives you Workbench tools; they run in the app as the user, with the user\u0027s own access. Only these tools are allowed by the sandbox policy (a call to any other is denied and logged):",
      (.tools.allowed[] | "- `\(.)`"),
      (if (.tools.denied | length) > 0 then "", "Not available here: \(.tools.denied | join(", "))." else empty end)
    else empty end' "${POLICY_SUMMARY}" > "${notes}/data-access.md"
  # --no-git-ignore: without it the CLI asks git whether the file is ignored, and the broker has no git.
  openshell sandbox upload --no-git-ignore "${SANDBOX_NAME}" "${notes}/data-access.md" "${AGENT_DATA_NOTES}" > /dev/null 2>&1 ||
    echo "Warning: could not write ${AGENT_DATA_NOTES} into the sandbox; the agent is not told what data it can read" >&2
  rm -rf "${notes}"
}

sandbox_phase() {
  openshell sandbox get "${SANDBOX_NAME}" -o json 2> /dev/null |
    jq -r '[.. | objects | .phase? | strings] | first // "unknown"' 2> /dev/null || true
}

ensure_sandbox() {
  wait_for_gateway
  ensure_policy
  # The provider may hold a token from before a restart; renew it now.
  renew_provider 2> /dev/null || true
  # OpenShell's full JSON audit records for every sandbox. Best effort.
  openshell settings set --global --key ocsf_json_enabled --value true > /dev/null 2>&1 || true
  if ! openshell sandbox get "${SANDBOX_NAME}" > /dev/null 2>&1; then
    echo "Creating sandbox ${SANDBOX_NAME} from ${SANDBOX_IMAGE} (policy: ${EFFECTIVE_POLICY})..." >&2
    # No trailing command: the harness starts with `sandbox exec`. Blocked connections are never
    # approved automatically (--approval-mode manual).
    local provider_args=()
    if want_provider; then
      ensure_provider
      provider_args=(--provider "${PROVIDER}")
    elif data_access_enabled; then
      echo "Data access is on but the metadata server gave this app no Google credential, so the sandbox starts without a cloud credential and without the data rules. When it answers again: agent-sandbox reset --yes" >&2
    fi
    # A harness with a web UI runs its server as the sandbox's main process.
    local serve_args=() serve_command=() pair
    if [[ -n "$(serve_port)" ]]; then
      harness_environment
      for pair in "${HARNESS_ENV[@]}"; do
        serve_args+=(--env "${pair}")
      done
      mapfile -t serve_command < <(jq -r '.serve.command[]' <<< "${HARNESS_JSON}")
      serve_args+=(--restart-policy always -- "${serve_command[@]}")
    fi
    openshell sandbox create --name "${SANDBOX_NAME}" --from "${SANDBOX_IMAGE}" \
      --policy "${RENDERED_POLICY}" --no-auto-providers --no-tty --detach \
      --approval-mode manual --label "harness=$(jq -r .name <<< "${HARNESS_JSON}")" ${provider_args[@]+"${provider_args[@]}"} \
      ${serve_args[@]+"${serve_args[@]}"} > /dev/null
    write_agent_data_notes
    ensure_forward
    return 0
  fi
  case "$(sandbox_phase)" in
    Stopped|stopped|STOPPED)
      echo "Starting stopped sandbox ${SANDBOX_NAME}..." >&2
      openshell sandbox start "${SANDBOX_NAME}" > /dev/null
      ;;
  esac
  ensure_forward
}

# HOME, and the image's venv ahead of the system Python.
readonly BASE_ENV=(
  HOME=/sandbox
  PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
)

# The model the harness must use: sent by the app (AGENT_MODEL_OVERRIDE), which has the GPU.
agent_model() {
  local model="${AGENT_MODEL_OVERRIDE:-${AGENT_MODEL:-}}"
  if [[ -z "${model}" ]]; then
    [[ -n "${AGENT_MODEL_COMMAND:-}" ]] || die "no model: set AGENT_MODEL, or AGENT_MODEL_COMMAND to a command that prints it"
    model="$(APP_USER_HOME="${USER_HOME_DIR}" ${AGENT_MODEL_COMMAND})" || die "${AGENT_MODEL_COMMAND} failed"
  fi
  [[ "${model}" =~ ^[[:alnum:]][[:alnum:]_.:/-]*$ ]] || die "invalid model tag: ${model}"
  printf '%s\n' "${model}"
}

# Fills HARNESS_ENV: the base environment, the harness's own, the model, and the output of the
# harness's config hook, which runs here, not in the sandbox.
HARNESS_ENV=()
harness_environment() {
  local model hook config_env config
  model="$(agent_model)"
  hook="$(jq -r '.config.hook // empty' <<< "${HARNESS_JSON}")"
  config_env="$(jq -r '.config.env // empty' <<< "${HARNESS_JSON}")"
  # A relative hook path is relative to the harness file's directory.
  if [[ -n "${hook}" && "${hook}" != /* ]]; then
    hook="$(dirname "${HARNESS}")/${hook}"
  fi
  HARNESS_ENV=("${BASE_ENV[@]}")
  mapfile -t -O "${#HARNESS_ENV[@]}" HARNESS_ENV < <(jq -r '.env | to_entries[] | "\(.key)=\(.value)"' <<< "${HARNESS_JSON}")
  HARNESS_ENV+=("MODEL_BASE_URL=${SANDBOX_MODEL_URL}" "AGENT_MODEL=${model}")
  if [[ -n "${hook}" ]]; then
    config="$(AGENT_MODEL="${model}" MODEL_BASE_URL="${SANDBOX_MODEL_URL}" AGENT_CONTEXT_LENGTH="${CONTEXT_LENGTH}" \
      AGENT_MCP_URL="${MCP_URL}" AGENT_POLICY_SUMMARY="${POLICY_SUMMARY}" \
      APP_USER_HOME="${USER_HOME_DIR}" "${hook}")" ||
      die "the harness config hook ${hook} failed"
    HARNESS_ENV+=("${config_env}=${config}")
  fi
}

exec_harness() {
  local tty_flag="$1"
  shift
  harness_environment
  local command=()
  mapfile -t command < <(jq -r '.command[]' <<< "${HARNESS_JSON}")
  openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" "${tty_flag}" -- \
    env "${HARNESS_ENV[@]}" "${command[@]}" "$@"
}

# The harness's web UI: a sandbox has no reachable listener, so its port is forwarded from this
# container and the app's front door proxies to it.
serve_port() {
  jq -r '.serve.port // empty' <<< "${HARNESS_JSON}"
}

forward_running() {
  local port="$1"
  openshell forward list 2> /dev/null | awk -v name="${SANDBOX_NAME}" -v port="${port}" \
    '$2 == name && $4 == port && $NF == "running" { found = 1 } END { exit !found }'
}

ensure_forward() {
  local port
  port="$(serve_port)"
  [[ -n "${port}" ]] || return 0
  # The app reaches the forward over the Compose network; the broker publishes no port.
  if ! forward_running "${port}"; then
    openshell forward start "0.0.0.0:${port}" "${SANDBOX_NAME}" --background > /dev/null 2>&1 ||
      echo "agent-sandbox: could not forward port ${port} of ${SANDBOX_NAME}; the web UI is not reachable (agent-sandbox web retries)" >&2
  fi
}

stop_forward() {
  local port
  port="$(serve_port)"
  [[ -n "${port}" ]] || return 0
  openshell forward stop "${port}" "${SANDBOX_NAME}" > /dev/null 2>&1 || true
}

cmd_web() {
  ensure_sandbox
  local port
  port="$(serve_port)"
  if [[ -z "${port}" ]]; then
    echo "Harness $(jq -r .name <<< "${HARNESS_JSON}") defines no web UI (no serve: in its harness file)."
    return 0
  fi
  if forward_running "${port}"; then
    echo "Web UI: ${SANDBOX_NAME} serves it on its port ${port}, forwarded here; open the app in Workbench to use it."
  else
    die "the forward to ${SANDBOX_NAME}:${port} is not running"
  fi
}

cmd_run() {
  ensure_sandbox
  exec_harness --tty "$@"
}

cmd_shell() {
  ensure_sandbox
  local env_args=()
  mapfile -t env_args < <(jq -r '.env | to_entries[] | "\(.key)=\(.value)"' <<< "${HARNESS_JSON}")
  openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" --tty -- \
    env "${BASE_ENV[@]}" ${env_args[@]+"${env_args[@]}"} bash -l
}

# One command in the sandbox, for scripts.
cmd_exec() {
  (( $# >= 1 )) || die "usage: agent-sandbox exec <command> [args]"
  ensure_sandbox
  local tty_flag=--no-tty
  [[ -t 0 && -t 1 ]] && tty_flag=--tty
  openshell sandbox exec "${SANDBOX_NAME}" --workdir "${SANDBOX_WORKDIR}" "${tty_flag}" -- \
    env "${BASE_ENV[@]}" "$@"
}

cmd_upload() {
  (( $# >= 1 && $# <= 2 )) || die "usage: agent-sandbox upload <path> [dest]"
  ensure_sandbox
  openshell sandbox upload --no-git-ignore "${SANDBOX_NAME}" "$1" "${2:-${SANDBOX_WORKDIR}}"
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
  openshell sandbox get "${SANDBOX_NAME}" 2>&1 || echo "  not created yet; \`agent-sandbox run\` creates it"
  echo
  echo "Base policy: ${POLICY}"
  echo "AI policy: ${AI_POLICY_FILE}"
  echo "Effective policy: ${EFFECTIVE_POLICY}"
  policy_explain
  local port
  port="$(serve_port)"
  if [[ -n "${port}" ]]; then
    if forward_running "${port}"; then
      echo "Web UI: forwarded from ${SANDBOX_NAME}:${port} (open the app in Workbench)"
    else
      echo "Web UI: not forwarded; run \`agent-sandbox web\`"
    fi
  fi
  echo
  echo "port-guard (${PORT_GUARD_STATUS}):"
  cat "${PORT_GUARD_STATUS}" 2> /dev/null || echo "  no status: the port-guard container has not written one"
}

cmd_policy() {
  case "${1:-}" in
    explain) policy_explain; return 0 ;;
  esac
  (( $# == 0 )) || die "usage: agent-sandbox policy [explain]"
  wait_for_gateway
  ensure_policy
  policy_explain >&2
  # A provider attaches only when a sandbox is created; its project variable
  # shows whether this sandbox has it.
  # shellcheck disable=SC2016 # Expanded inside the sandbox, not here.
  if data_access_enabled && openshell sandbox get "${SANDBOX_NAME}" > /dev/null 2>&1 &&
    ! openshell sandbox exec "${SANDBOX_NAME}" --no-tty -- sh -c 'test -n "${GCP_PROJECT_ID:-}"' > /dev/null 2>&1; then
    echo "Note: this sandbox was created before data access was on, so it has no Google credential provider." >&2
    echo "      Run \`agent-sandbox reset --yes\` once to attach it." >&2
  fi
  openshell policy set "${SANDBOX_NAME}" --policy "${RENDERED_POLICY}" --wait
  write_agent_data_notes
  echo "Network rules are live. Filesystem and process changes need \`agent-sandbox reset --yes\`."
}

cmd_logs() {
  wait_for_gateway
  openshell logs "${SANDBOX_NAME}" --source sandbox -n "${1:-100}"
}

# Saves the sandbox's last 2,000 log lines: the gateway keeps no more, in memory, and drops
# them when the sandbox is deleted. Prints the file it wrote.
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
}

cmd_audit() {
  wait_for_gateway
  local saved
  case "${1:-}" in
    save)
      saved="$(audit_save)"
      [[ -n "${saved}" ]] || die "nothing to save: the sandbox has no log"
      echo "${saved}"
      ;;
    *) die "usage: agent-sandbox audit save (audit export runs in the app, which copies to the bucket)" ;;
  esac
}

cmd_reset() {
  [[ "${1:-}" == "--yes" ]] ||
    die "reset deletes the sandbox and every file in it. Download what you need, then run: agent-sandbox reset --yes"
  wait_for_gateway
  # Create the provider first, so a failure keeps the old sandbox.
  if want_provider; then
    ensure_provider
  fi
  # Deleting the sandbox drops its log from the gateway.
  local saved
  saved="$(audit_save 2> /dev/null || true)"
  if [[ -n "${saved}" ]]; then
    echo "Saved the audit log before deleting the sandbox:" >&2
    echo "${saved}" >&2
  fi
  stop_forward
  openshell sandbox delete "${SANDBOX_NAME}" > /dev/null 2>&1 || true
  ensure_sandbox
  echo "Created a new sandbox ${SANDBOX_NAME}."
}

# selftest.sh uses this script's functions and variables.
cmd_selftest() {
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/selftest.sh"
  run_selftest
}

main() {
  command -v openshell > /dev/null 2>&1 || die "the openshell CLI is not installed"
  local subcommand="${1:-run}"
  if (( $# > 0 )); then
    shift
  fi
  case "${subcommand}" in
    -h|--help|help) usage; return 0 ;;
  esac
  load_harness
  case "${subcommand}" in
    run) cmd_run "$@" ;;
    shell) cmd_shell ;;
    exec) cmd_exec "$@" ;;
    upload) cmd_upload "$@" ;;
    download) cmd_download "$@" ;;
    status) cmd_status ;;
    web) cmd_web ;;
    policy) cmd_policy "$@" ;;
    logs) cmd_logs "$@" ;;
    audit) cmd_audit "$@" ;;
    reset) cmd_reset "$@" ;;
    selftest) cmd_selftest ;;
    credential) cmd_credential "$@" ;;
    *) usage >&2; exit 1 ;;
  esac
}

main "$@"
