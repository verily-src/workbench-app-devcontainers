#!/bin/bash

# Lifecycle hooks run as root after Workbench authentication and mounts.
set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1:?Usage: start-services.sh <username> <user-home-dir>}"
readonly USER_HOME_DIR="${2:?Usage: start-services.sh <username> <user-home-dir>}"
# This script is bind-mounted alone from the app folder (docker-compose.yaml); everything it
# starts is a feature installed in the image.
export APP_USER_HOME="${USER_HOME_DIR}"

# vLLM runs as the user: its state, compile cache, model store and log must be
# user-owned, including on upgrade from an app that created them as root.
mkdir -p "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache"
touch "${USER_HOME_DIR}/vllm-server.log"
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache"
chown "${USER_NAME}:${USER_NAME}" "${USER_HOME_DIR}/vllm-server.log"

# As the authenticated user, so the MCP server sees the user's wb tokens.
sudo -H -u "${USER_NAME}" /opt/wb-mcp-server/start-server.sh

# Publish the user's key for the sandbox-broker now, so the first command does not wait on it.
sudo -H -u "${USER_NAME}" --preserve-env=APP_USER_HOME bash -c '
  set -e
  key="${APP_USER_HOME}/.ssh/sandbox-broker"
  if [[ ! -f "${key}" ]]; then
    mkdir -p "${APP_USER_HOME}/.ssh" && chmod 700 "${APP_USER_HOME}/.ssh"
    ssh-keygen -q -t ed25519 -N "" -C sandbox-broker -f "${key}"
  fi
  mkdir -p "${APP_USER_HOME}/openshell"
  install -m 644 "${key}.pub" "${APP_USER_HOME}/openshell/broker.pub"'
# Who may use the assistant, and which of its features (the ai-policy README, "Access and
# features"): the person's Workbench groups, read as the person. The state file is a volume of
# its own that the broker and the assistant UI mount read-only.
readonly ACCESS="/opt/ai-policy/access.py"
readonly ACCESS_STATE="${AGENT_ACCESS_STATE:-${USER_HOME_DIR}/.ara/access.json}"
mkdir -p "$(dirname "${ACCESS_STATE}")"
chown "${USER_NAME}:${USER_NAME}" "$(dirname "${ACCESS_STATE}")"
chmod 755 "$(dirname "${ACCESS_STATE}")"

# Against the image's access.yaml only: nothing in the environment changes the groups.
check_access() {
  sudo -H -u "${USER_NAME}" python3 "${ACCESS}" resolve --config-dir /opt/agent-sandbox/config --state "${ACCESS_STATE}"
}

feature_on() {
  jq -e --arg f "$1" '.features[$f] == true' "${ACCESS_STATE}" > /dev/null 2>&1
}

# Everything the assistant needs, for a person the access check admitted.
start_assistant() {
  # The model: the local Nemotron model when this machine runs it (two H100) or vLLM already
  # answers for it (the Vertex AI proxy on the same port lists the same model, owned by vertex-ai,
  # and does not count). Otherwise, only for a person with the vertex_model feature (alpha, never inside
  # a data perimeter): the Nemotron model a Vertex AI endpoint in the workspace's project serves
  # (VERTEX_ENDPOINT, the vertex-model feature), else Gemini on Vertex AI (VERTEX_MODEL). Otherwise
  # none, and the page says why.
  local gpus vllm_up=() backend endpoint="" endpoint_model=""
  gpus="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2> /dev/null || true)"
  if curl -fsS -m 5 "http://127.0.0.1:${VLLM_PORT:-8000}/v1/models" 2> /dev/null |
      jq -e --arg m "${VLLM_MODEL:-}" 'any(.data[]?; .id == $m and .owned_by != "vertex-ai")' > /dev/null 2>&1; then
    vllm_up=(--vllm-up)
  fi
  # The workspace's endpoint, looked up as the app's user (one or two API calls), only for a person
  # who may use it. access.py uses it only when the local model can't run here.
  if [[ ${#vllm_up[@]} -eq 0 && -n "${VERTEX_ENDPOINT:-}" && "${VERTEX_ENDPOINT}" != "off" ]] &&
      feature_on vertex_model; then
    if endpoint="$(sudo -H -u "${USER_NAME}" --preserve-env=VERTEX_ENDPOINT,VERTEX_ENDPOINT_LOCATION,GOOGLE_CLOUD_PROJECT \
        python3 /opt/vertex-model/proxy.py find-endpoint)"; then
      endpoint_model="$(jq -r '.model // empty' <<< "${endpoint}")"
      echo "Vertex AI endpoint: ${endpoint_model} at $(jq -r '.url' <<< "${endpoint}")."
    else
      endpoint=""
    fi
  fi
  backend="$(sudo -H -u "${USER_NAME}" python3 "${ACCESS}" model --state "${ACCESS_STATE}" --gpus "${gpus}" \
    ${vllm_up[@]+"${vllm_up[@]}"} --vertex-model "${VERTEX_MODEL:-}" \
    --vllm-model "${VLLM_MODEL:-}" --endpoint-model "${endpoint_model}")" || {
    echo "access.py could not choose a model for the assistant." >&2
    return 1
  }
  echo "Model: ${backend} ($(jq -r '.model.reason' "${ACCESS_STATE}"))."

  designer_provider=""
  case "${backend}" in
    endpoint)
      # The vertex-model feature answers on vLLM's port with the endpoint's model, no GPU needed.
      # The endpoint runs vLLM, so the cohort designer keeps its usual provider, on that port.
      export VLLM_MODEL="${endpoint_model}" VERTEX_MODEL="${endpoint_model}"
      VERTEX_ENDPOINT_URL="$(jq -r '.url' <<< "${endpoint}")"
      export VERTEX_ENDPOINT_URL
      local served_context
      served_context="$(jq -r '.context // 0' <<< "${endpoint}")"
      if (( served_context > 0 )); then
        export VLLM_CONTEXT_LENGTH="${served_context}"
      fi
      # By `env`: sudo reads /etc/environment, which holds compose's VERTEX_MODEL (Gemini) and
      # VLLM_CONTEXT_LENGTH, over what --preserve-env keeps.
      sudo -H -u "${USER_NAME}" --preserve-env=GOOGLE_CLOUD_PROJECT,VLLM_PORT,VLLM_BIND_ADDRESS \
        env VERTEX_MODEL="${endpoint_model}" VERTEX_ENDPOINT_URL="${VERTEX_ENDPOINT_URL}" \
        VLLM_CONTEXT_LENGTH="${VLLM_CONTEXT_LENGTH:-262144}" /opt/vertex-model/start-server.sh || {
        echo "The Vertex AI proxy did not start; see ${USER_HOME_DIR}/.vertex-model/server.log." >&2
        return 1
      }
      ;;
    vertex)
      # The vertex-model feature answers on vLLM's port with that Gemini model, no GPU needed,
      # and the model's name below is that one. The cohort designer then runs on its own
      # Gemini provider instead (its README).
      export VLLM_MODEL="${VERTEX_MODEL}"
      designer_provider="gemini"
      sudo -H -u "${USER_NAME}" \
        --preserve-env=VERTEX_MODEL,VERTEX_LOCATION,GOOGLE_CLOUD_PROJECT,VLLM_PORT,VLLM_BIND_ADDRESS,VLLM_CONTEXT_LENGTH \
        /opt/vertex-model/start-server.sh || {
        echo "The Vertex AI proxy did not start; see ${USER_HOME_DIR}/.vertex-model/server.log." >&2
        return 1
      }
      ;;
    vllm)
      # Nothing below may take the Vertex AI path.
      export VERTEX_MODEL=""
      # vLLM (the vllm-model feature). Preserve its settings across sudo; keep logs and cached
      # weights user-owned.
      sudo -H -u "${USER_NAME}" \
        --preserve-env=APP_USER_HOME,VLLM_MODEL,VLLM_PORT,VLLM_BIND_ADDRESS,VLLM_MODELS,VLLM_CONTEXT_LENGTH,VLLM_GPU_MEMORY_UTILIZATION,VLLM_MAX_NUM_SEQS,VLLM_LOAD_TIMEOUT_MINUTES,VLLM_EXTRA_ARGS,VLLM_HTTP_TIMEOUT_KEEP_ALIVE \
        /opt/vllm-model/start-vllm.sh || {
        echo "vLLM did not start; see ${USER_HOME_DIR}/vllm-server.log." >&2
        return 1
      }
      ;;
    none)
      echo "No model for the assistant: $(jq -r '.model.message' "${ACCESS_STATE}")" >&2
      return 0
      ;;
    *)
      echo "access.py chose no known model backend (got '${backend}'); the assistant's model did not start." >&2
      return 1
      ;;
  esac

  # The cohort designer, on the model just started and the workspace's datasets. Best effort: a
  # workspace with no BigQuery dataset has nothing for it to read, and the app works without it.
  # The model's name goes by `env`, so the designer gets the one exported above whatever sudo keeps
  # of the environment.
  if feature_on cohort_designer && ! sudo -H -u "${USER_NAME}" --preserve-env=VLLM_PORT,VLLM_CONTEXT_LENGTH,COHORT_DESIGNER_DATASETS \
      env VLLM_MODEL="${VLLM_MODEL}" COHORT_DESIGNER_PROVIDER="${designer_provider}" \
      COHORT_DESIGNER_REGION="${VERTEX_LOCATION:-global}" /opt/cohort-designer/start-server.sh; then
    echo "The cohort designer is not running; see ${USER_HOME_DIR}/.cohort-designer/server.log, then run /opt/cohort-designer/start-server.sh." >&2
  fi

  # The Kumo forecast server, which reads the designer's locked cohorts. Best effort, as above.
  if feature_on kumo_forecast && ! sudo -H -u "${USER_NAME}" \
      --preserve-env=KUMO_FORECAST_GPU_GB,KUMO_FORECAST_CONTEXT,KUMO_FORECAST_ESTIMATORS,KUMO_FORECAST_MAX_ROWS,KUMO_FORECAST_BILLING_PROJECT,KUMO_FORECAST_SMALL_CELL,KUMO_FORECAST_SAMPLE_RECORDS \
      /opt/kumo-forecast/start-server.sh; then
    echo "The Kumo forecast server is not running; see ${USER_HOME_DIR}/.kumo-forecast/server.log, then run /opt/kumo-forecast/start-server.sh." >&2
  fi

  # Create the sandbox and forward its web UI now, so opening the app does not wait on a first
  # `opencode`. Best effort: any later agent-sandbox command re-establishes the forward.
  if ! sudo -H -u "${USER_NAME}" --preserve-env=APP_USER_HOME,AGENT_BROKER,AGENT_MODEL_COMMAND,VERTEX_MODEL,VLLM_MODEL \
      /usr/local/bin/agent-sandbox web; then
    echo "The web UI is not up yet; run \`agent-sandbox web\` in a terminal." >&2
  fi

  reconnect_tools
}

# OpenCode in the sandbox connects to the MCP servers once, when it starts, and does not retry. On a
# restart the sandbox can come back before the servers above are up (Kumo takes minutes to load),
# and their tools stay off. Once OpenCode answers (up to 3 min), reconnect each server it marks
# failed, and keep trying those that still fail every 30 s, up to 10 attempts (about 4.5 min plus
# the time each attempt takes). Best effort.
reconnect_tools() {
  local opencode="${OPENCODE_URL:-http://sandbox-broker:4096}" status="" name failed
  for _ in $(seq 18); do
    status="$(curl -fsS -m 10 "${opencode}/mcp" 2> /dev/null)" && break
    sleep 10
  done
  [[ -n "${status}" ]] || { echo "OpenCode did not answer; its tools were not checked." >&2; return 0; }
  for attempt in $(seq "${RECONNECT_ATTEMPTS:-10}"); do
    failed="$(jq -r 'to_entries[] | select(.value.status == "failed") | .key' <<< "${status}" 2> /dev/null)"
    [[ -n "${failed}" ]] || return 0
    (( attempt == 1 )) || sleep "${RECONNECT_SECONDS:-30}"
    for name in ${failed}; do
      [[ "${name}" =~ ^[a-z][a-z0-9]*$ ]] || continue
      curl -fsS -m 30 -X POST -H 'Content-Type: application/json' -d '{}' "${opencode}/mcp/${name}/disconnect" > /dev/null 2>&1 || true
      curl -fsS -m 60 -X POST -H 'Content-Type: application/json' -d '{}' "${opencode}/mcp/${name}/connect" > /dev/null 2>&1 || true
    done
    status="$(curl -fsS -m 10 "${opencode}/mcp" 2> /dev/null)" || status="{}"
    for name in ${failed}; do
      if jq -e --arg n "${name}" '.[$n].status == "connected"' <<< "${status}" > /dev/null 2>&1; then
        echo "Reconnected the ${name} tools in OpenCode."
      fi
    done
  done
  failed="$(jq -r 'to_entries[] | select(.value.status == "failed") | .key' <<< "${status}" 2> /dev/null)"
  for name in ${failed}; do
    echo "Could not reconnect the ${name} tools in OpenCode; its server log says why." >&2
  done
}

# A person the check admits gets the assistant now. Otherwise the page says why (not admitted, or
# the check could not be made), and a background loop rechecks until the person is admitted (every
# five minutes, or two while wb cannot answer), then starts the assistant: someone added to a group
# does not have to restart the app. An invalid access.yaml or features.yaml is not retried.
admitted() {
  [[ -n "$(jq -r '.tier // empty' "${ACCESS_STATE}" 2> /dev/null)" ]]
}

# Workbench runs this script from both postCreateCommand and postStartCommand, so two runs can
# overlap on an app's first start. The model servers only notice one another once a model answers,
# which takes minutes, so the assistant starts at most once per container start: under a lock, and
# only if this start has not started it. One recheck loop runs at a time. The lock files'
# descriptors are closed for everything started, so a server left running does not hold them.
# The locks sit beside the access state. The two markers (the assistant started; access resolved)
# sit in a tmpfs directory of this container, which a container restart empties: a restarted
# container has none of the processes the markers speak of, so it starts again. The markers hold
# the host's boot_id, which containers share; where it cannot be read it is "unknown", which
# matches for as long as the directory lives.
LOCKS="$(dirname "${ACCESS_STATE}")"
readonly LOCKS
readonly MARKERS="${START_MARKERS:-/dev/shm/ara-start}"
readonly STARTED="${MARKERS}/assistant-started"
readonly RESOLVED="${MARKERS}/access-resolved"
mkdir -p "${MARKERS}"
boot_id="$(cat /proc/sys/kernel/random/boot_id 2> /dev/null || echo unknown)"
readonly BOOT_ID="${boot_id}"

# The first check of a container start runs without the last start's state: until it finishes
# (up to 180 s), readers see "checking" rather than an admission the person may have lost. The
# rechecks keep the last state while they run. Nothing in the state is needed across starts: the
# model is chosen again at each start.
forget_old_access() {
  (
    flock 7
    if [[ "$(cat "${RESOLVED}" 2> /dev/null)" != "${BOOT_ID}" ]]; then
      rm -f "${ACCESS_STATE}"
      echo "${BOOT_ID}" > "${RESOLVED}"
    fi
  ) 7> "${LOCKS}/boot.lock"
}

start_once() {
  (
    flock 9
    if [[ "$(cat "${STARTED}" 2> /dev/null)" == "${BOOT_ID}" ]]; then
      echo "The assistant was already started on this boot."
      exit 0
    fi
    # A model that did not start leaves the boot unmarked, so running this script again retries.
    # The page says the model did not start.
    if start_assistant 8>&- 9>&-; then
      echo "${BOOT_ID}" > "${STARTED}"
    else
      echo "The assistant did not start: its model is not running. Run start-services.sh again to retry." >&2
      sudo -H -u "${USER_NAME}" python3 "${ACCESS}" model-failed --state "${ACCESS_STATE}" \
        --message "The Research Assistant couldn't start. Please try again later." || true
      exit 1
    fi
  ) 9> "${LOCKS}/start.lock"
}

forget_old_access
assistant_rc=0
access_rc=0
check_access || access_rc=$?
if (( access_rc == 0 )) && admitted; then
  start_once || assistant_rc=$?
elif (( access_rc == 1 )); then
  echo "Not starting the assistant: the access or feature configuration is invalid." >&2
else
  log="${USER_HOME_DIR}/ai-research-assistant-access.log"
  echo "Not starting the assistant yet: $(jq -r '.message' "${ACCESS_STATE}" 2> /dev/null)" >&2
  echo "Rechecking access in the background (${log})." >&2
  (
    flock -n 8 || { echo "$(date -u +%FT%TZ) another recheck loop is running."; exit 0; }
    rc="${access_rc}"
    while [[ "$(cat "${STARTED}" 2> /dev/null)" != "${BOOT_ID}" ]]; do
      if (( rc == 0 )); then sleep "${ACCESS_RECHECK_SECONDS:-300}"; else sleep "${ACCESS_RETRY_SECONDS:-120}"; fi
      rc=0
      check_access || rc=$?
      if (( rc == 0 )) && admitted; then
        echo "$(date -u +%FT%TZ) admitted as $(jq -r '.tier' "${ACCESS_STATE}"); starting the assistant."
        start_once || exit 1
        exit 0
      fi
      (( rc == 1 )) && { echo "$(date -u +%FT%TZ) the configuration is invalid; not rechecking."; exit 1; }
    done
  ) 8> "${LOCKS}/recheck.lock" > "${log}" 2>&1 < /dev/null &
  disown
fi

# The script still ends well when the assistant did not start: Workbench runs it as the app's
# lifecycle command, and a failure there fails the whole app, page included.
if (( assistant_rc != 0 )); then
  echo "start-services.sh: the assistant did not start (see above); the page says so." >&2
fi
