#!/bin/bash

# The agent-sandbox self-test. Sourced by agent-sandbox.sh, whose functions and variables it uses.

PASSED=0
FAILED=0

# The VM's internal IP, for checking from another VM that code-server is closed.
vm_internal_ip() {
  curl -fsS -m 3 -H 'Metadata-Flavor: Google' \
    http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip 2> /dev/null ||
    echo "<this VM's internal IP>"
}

# port-guard's status must be recent and report the rule in place.
check_port_guard() {
  local label="the app's port is closed to other VMs (port-guard rule in place)"
  if [[ ! -d "$(dirname "${PORT_GUARD_STATUS}")" ]]; then
    echo "SKIP  ${label} (${PORT_GUARD_STATUS} is not mounted)"
    return 0
  fi
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

# Each request is sent from inside the sandbox by data-probe.py, which prints "denied" when
# OpenShell blocks it. Nothing is written: the write checks send requests Google refuses, so an
# allowed one answers HTTP 400 and a blocked one never leaves the sandbox.
selftest_data_access() {
  if [[ "$(jq -r '.data.enabled' "${POLICY_SUMMARY}" 2> /dev/null)" != true ]]; then
    echo "SKIP  data checks: the last render allowed no data ($(jq -r '.notes | map(select(startswith("data"))) | first // "no summary"' "${POLICY_SUMMARY}" 2> /dev/null))"
    return 0
  fi
  local project python dataset_project dataset owned_dataset_project owned_dataset bucket owned_bucket write
  # Fields are separated by "|": any of them may be blank.
  IFS='|' read -r project python write dataset_project dataset owned_dataset_project owned_dataset bucket owned_bucket < <(jq -r '
    [.data.project, .data.python, (.data.write | tostring),
     ((.data.datasets | map(select(.write | not)) | first) // {} | .project // ""),
     ((.data.datasets | map(select(.write | not)) | first) // {} | .dataset // ""),
     ((.data.datasets | map(select(.write)) | first) // {} | .project // ""),
     ((.data.datasets | map(select(.write)) | first) // {} | .dataset // ""),
     ((.data.buckets | map(select(.write | not)) | first) // {} | .name // ""),
     ((.data.buckets | map(select(.write)) | first) // {} | .name // "")] | join("|")' "${POLICY_SUMMARY}")
  # The probe must run on the interpreter the data rules name; the image's venv resolves to it.
  if [[ "${python}" == /usr/bin/python3.11 ]]; then
    python=/opt/venv/bin/python
  fi
  if ! openshell sandbox exec "${SANDBOX_NAME}" --no-tty -- "${python}" -c 'import google.auth, google.cloud.bigquery' \
    > /dev/null 2>&1; then
    echo "SKIP  data checks: ${python} (the interpreter the data rules name) can't import the Google client libraries"
    return 0
  fi
  local probe="${python} /opt/agent-sandbox/data-probe.py"
  local bq="https://bigquery.googleapis.com/bigquery/v2/projects"
  local gcs="https://storage.googleapis.com"

  # shellcheck disable=SC2016 # Expanded inside the sandbox.
  check "Google token in the sandbox is a placeholder" "placeholder" \
    'case "${GCP_ADC_ACCESS_TOKEN:-}" in openshell:resolve:*) echo placeholder;; "") echo missing;; *) echo REAL-TOKEN;; esac'
  check "BigQuery query runs with the Python client" "rows=1" \
    "${probe} --query 'SELECT 1' ${project}"
  check "datasets of the workspace project can be listed" "HTTP 200" "${probe} GET ${bq}/${project}/datasets"
  if [[ -n "${dataset}" ]]; then
    check "a read-only dataset (${dataset}) can be looked up" "HTTP 200" "${probe} GET ${bq}/${dataset_project}/datasets/${dataset}"
    check "a read-only dataset's tables can't be deleted" "denied" \
      "${probe} DELETE ${bq}/${dataset_project}/datasets/${dataset}/tables/selftest-missing"
    check "rows can't be streamed into a read-only dataset (insertAll)" "denied" \
      "${probe} POST ${bq}/${dataset_project}/datasets/${dataset}/tables/selftest-missing/insertAll '{\"rows\":[]}'"
  fi
  if [[ -n "${owned_dataset}" ]]; then
    check "an owned dataset (${owned_dataset}) can be looked up" "HTTP 200" "${probe} GET ${bq}/${owned_dataset_project}/datasets/${owned_dataset}"
    check "an owned dataset's tables are writable through the policy (Google answers, not OpenShell)" "HTTP 4" \
      "${probe} DELETE ${bq}/${owned_dataset_project}/datasets/${owned_dataset}/tables/selftest-missing"
  fi
  check "queries can't be billed to another project" "denied" \
    "${probe} POST ${bq}/bigquery-public-data/queries '{\"query\":\"SELECT 1\",\"useLegacySql\":false}'"
  check "curl can't reach BigQuery (only the Python client)" "blocked" \
    "curl -sS -m 10 -o /dev/null ${bq}/${project}/datasets 2> /dev/null && echo reachable || echo blocked"
  if [[ -n "${bucket}" ]]; then
    check "a read-only bucket (${bucket}) can be read" "HTTP 200" "${probe} GET ${gcs}/storage/v1/b/${bucket}/o"
    check "a read-only bucket can't be written" "denied" \
      "${probe} POST '${gcs}/upload/storage/v1/b/${bucket}/o?uploadType=media' x"
  fi
  if [[ -n "${owned_bucket}" ]]; then
    check "an owned bucket (${owned_bucket}) can be read" "HTTP 200" "${probe} GET ${gcs}/storage/v1/b/${owned_bucket}/o"
    check "an owned bucket is writable through the policy (Google answers, not OpenShell)" "HTTP 4" \
      "${probe} POST '${gcs}/upload/storage/v1/b/${owned_bucket}/o?uploadType=media' x"
  fi
  if [[ "${write}" != true ]]; then
    echo "SKIP  write checks: ai-policy.yaml data.write is none"
  fi
  check "other buckets can't be read" "denied" \
    "${probe} GET ${gcs}/storage/v1/b/selftest-not-approved-${project}/o"
}

# Sent with curl, which the tools rule lists for this purpose.
selftest_tools() {
  if [[ -z "${MCP_URL}" ]]; then
    echo "SKIP  Workbench tools checks: this app exposes no MCP server to the sandbox (AGENT_MCP_URL)"
    return 0
  fi
  local allowed denied
  allowed="$(jq -r 'if .tools.enabled then .tools.allowed[0] // empty else empty end' "${POLICY_SUMMARY}" 2> /dev/null || true)"
  denied="$(jq -r '.tools.denied[0] // empty' "${POLICY_SUMMARY}" 2> /dev/null || true)"
  if [[ -z "${allowed}" ]]; then
    check "Workbench tools are blocked (the policy allows none)" "blocked" \
      "curl -sS -m 10 -o /dev/null -X POST ${MCP_URL} -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' 2> /dev/null && echo reachable || echo blocked"
    return 0
  fi
  check "Workbench MCP server lists its tools" '"tools"' \
    "curl -sS -m 20 -X POST ${MCP_URL} -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"
  if [[ -n "${denied}" ]]; then
    check "a denied Workbench tool (${denied}) is blocked" "blocked" \
      "code=\$(curl -sS -m 20 -o /dev/null -w '%{http_code}' -X POST ${MCP_URL} -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"${denied}\",\"arguments\":{}}}' 2> /dev/null); [ \"\$code\" = 200 ] && echo allowed || echo \"blocked (HTTP \$code)\""
  fi
  check "an unlisted method (resources/list) is blocked" "blocked" \
    "code=\$(curl -sS -m 20 -o /dev/null -w '%{http_code}' -X POST ${MCP_URL} -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"resources/list\"}' 2> /dev/null); [ \"\$code\" = 200 ] && echo allowed || echo \"blocked (HTTP \$code)\""
}

run_selftest() {
  ensure_sandbox
  local model
  model="$(agent_model)"
  local models="${SANDBOX_MODEL_HOST}"
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
  check "the app's front door on the VM is blocked" "blocked" \
    'curl -sS -m 5 -o /dev/null http://host.openshell.internal:8080/ 2> /dev/null && echo reachable || echo blocked'
  check "OpenShell gateway is blocked" "blocked" \
    'curl -sS -m 5 -o /dev/null http://host.openshell.internal:8090/ 2> /dev/null && echo reachable || echo blocked'
  check "vLLM raw completions (/v1/completions) are blocked" "blocked" \
    "code=\$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -X POST ${models}/v1/completions -H 'Content-Type: application/json' -d '{\"model\":\"${model}\",\"prompt\":\"x\",\"max_tokens\":1}' 2> /dev/null); [ \"\$code\" = 200 ] && echo allowed || echo \"blocked (HTTP \$code)\""
  check "other vLLM endpoints (/metrics) are blocked" "blocked" \
    "code=\$(curl -sS -m 10 -o /dev/null -w '%{http_code}' ${models}/metrics 2> /dev/null); [ \"\$code\" = 200 ] && echo allowed || echo \"blocked (HTTP \$code)\""
  check "local model chat endpoint answers" '"choices"' \
    "curl -sS -m 170 ${models}/v1/chat/completions -H 'Content-Type: application/json' -d '${chat_body}'"

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
    if have_metadata_credential; then
      selftest_data_access
    else
      echo "SKIP  data checks: the metadata server gave this app no Google credential"
    fi
  fi

  selftest_tools

  local web_port
  web_port="$(serve_port)"
  if [[ -n "${web_port}" ]]; then
    if [[ "$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${web_port}/" 2> /dev/null)" == 200 ]]; then
      PASSED=$((PASSED + 1))
      echo "PASS  web UI answers through the forward (port ${web_port})"
    else
      FAILED=$((FAILED + 1))
      echo "FAIL  web UI answers through the forward (port ${web_port})"
      echo "      no HTTP 200 from 127.0.0.1:${web_port}; run \`agent-sandbox web\` and check the app's front door"
    fi
  fi

  # An unreadable Workbench renders no data rules: safe, but the agent has no data.
  if [[ -s "${WORKSPACE_DATA}" ]] && [[ "$(jq -r .unavailable "${WORKSPACE_DATA}")" == "false" ]]; then
    PASSED=$((PASSED + 1))
    printf 'PASS  workspace resources read from Workbench (%s datasets and buckets)\n' \
      "$(jq -r '.resources | length' "${WORKSPACE_DATA}")"
  else
    FAILED=$((FAILED + 1))
    printf 'FAIL  workspace resources read from Workbench\n      %s\n' \
      "$(jq -r '.errors | join("; ")' "${WORKSPACE_DATA}" 2> /dev/null || echo "no ${WORKSPACE_DATA}")"
  fi

  check_port_guard

  echo
  echo "${PASSED} passed, ${FAILED} failed"
  echo
  echo "This app can't test its own network card. To confirm its port is closed, run from another"
  echo "app in the workspace (it should time out, not return HTTP 302):"
  printf '  curl -m 5 -o /dev/null -w "%%{http_code}\\n" http://%s:8080/\n' "$(vm_internal_ip)"
  (( FAILED == 0 ))
}
