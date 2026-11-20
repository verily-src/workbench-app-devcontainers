#!/usr/bin/env bash

# install.sh installs the cohort designer and its MCP server (README.md).

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly USERNAME="${USERNAME:-"root"}"
USER_HOME_DIR="${USERHOMEDIR:-"/home/${USERNAME}"}"
if [[ "${USER_HOME_DIR}" == "/home/root" ]]; then
    USER_HOME_DIR="/root"
fi
readonly USER_HOME_DIR
readonly DESIGNER_PORT="${PORT:-"9243"}"
readonly DESIGNER_BIND_ADDRESS="${BINDADDRESS:-"127.0.0.1"}"
readonly ROLE="${ROLE:-"app"}"
readonly RELEASE="${RELEASE:-"gs://cda-wb-beaming-kiwi-9470/cohort-designer/0.1.0/cohort-designer-linux-x86_64"}"
readonly SHA256="${SHA256:-"9ea81d7f92fca2858f6af27dc4d7bedce3af1227a91f640f01007206bf2ca99e"}"

readonly INSTALL_DIR="/opt/cohort-designer"
readonly SANDBOX_DIR="/opt/agent-sandbox"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

case "${ROLE}" in
    app|broker) ;;
    *) echo "Error: role must be app or broker, got '${ROLE}'."; exit 1 ;;
esac

# The catalog the sandbox's policy is rendered from. agent-sandbox reads every file here.
mkdir -p "${SANDBOX_DIR}/mcp.d"
install -m 644 "${FEATURE_DIR}/sandbox/cohort.yaml" "${SANDBOX_DIR}/mcp.d/cohort.yaml"
if [[ "${ROLE}" == broker ]]; then
    echo "cohort-designer: catalog installed in ${SANDBOX_DIR}/mcp.d (role broker)"
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
if ! command -v curl > /dev/null 2>&1 || ! command -v jq > /dev/null 2>&1; then
    apt-get update -y
    apt-get -y install --no-install-recommends ca-certificates curl jq
    rm -rf /var/lib/apt/lists/*
fi

# The designer is a single binary released apart from this repository (README.md, "The binary"):
# fetched here and checked against its sha256. A build that cannot read the release leaves the
# fetch to the first start-server.sh, which runs as the user.
mkdir -p "${INSTALL_DIR}/bin"
install -m 755 "${FEATURE_DIR}/fetch-designer.sh" "${INSTALL_DIR}/fetch-designer.sh"
if ! "${INSTALL_DIR}/fetch-designer.sh" "${RELEASE}" "${SHA256}" "${INSTALL_DIR}/bin/cohort-designer"; then
    echo "cohort-designer: the release could not be fetched at build; start-server.sh fetches it." >&2
fi

cat > "${INSTALL_DIR}/start-server.sh" <<START
#!/bin/bash
# Starts the cohort designer's MCP server as a background daemon, as the app's user: it reads
# BigQuery with that user's Application Default Credentials. Run it after the model server is
# up and Workbench is logged in. Settings: COHORT_DESIGNER_BIND, COHORT_DESIGNER_PORT,
# COHORT_DESIGNER_MODEL_URL (default the local vLLM), COHORT_DESIGNER_MODEL (default the model
# vLLM serves), COHORT_DESIGNER_CONTEXT (default VLLM_CONTEXT_LENGTH), COHORT_DESIGNER_DATASETS
# (project.dataset, comma-separated: read only these of the workspace's datasets),
# COHORT_DESIGNER_PROVIDER (gemini: Gemini on Vertex AI in the workspace's project, in place of the
# local server) and COHORT_DESIGNER_REGION (its Vertex AI location, default global).

set -o errexit
set -o nounset
set -o pipefail

readonly DIR="${INSTALL_DIR}"
readonly STATE="\${COHORT_DESIGNER_STATE:-\${HOME}/.cohort-designer}"
readonly PORT="\${COHORT_DESIGNER_PORT:-${DESIGNER_PORT}}"
readonly BIND="\${COHORT_DESIGNER_BIND:-${DESIGNER_BIND_ADDRESS}}"
readonly MODEL_URL="\${COHORT_DESIGNER_MODEL_URL:-http://127.0.0.1:\${VLLM_PORT:-8000}/v1}"
readonly CONTEXT="\${COHORT_DESIGNER_CONTEXT:-\${VLLM_CONTEXT_LENGTH:-65536}}"
readonly LOGFILE="\${STATE}/server.log"
readonly RUNNING="bin/cohort-designer serve --config"

if pgrep -f "\${RUNNING}" > /dev/null; then
  echo "The cohort designer is already running."
  exit 0
fi
mkdir -p "\${STATE}" && chmod 700 "\${STATE}"

# The binary the build fetched, or else one fetched now into the user's state folder.
bin="\${DIR}/bin/cohort-designer"
if [[ ! -x "\${bin}" ]]; then
  bin="\${STATE}/bin/cohort-designer"
  "\${DIR}/fetch-designer.sh" "${RELEASE}" "${SHA256}" "\${bin}"
fi

model="\${COHORT_DESIGNER_MODEL:-\${VLLM_MODEL:-}}"
if [[ -z "\${model}" ]]; then
  echo "cohort-designer: no model to run on (COHORT_DESIGNER_MODEL or VLLM_MODEL)." >&2
  exit 1
fi

# The workspace's datasets, read again at every start. With none the designer has nothing to
# read and is not started (make-config exits 3).
"\${bin}" make-config "\${STATE}/config.yaml" \\
  --model "\${model}" --base-url "\${MODEL_URL}" --context "\${CONTEXT}" \\
  \${COHORT_DESIGNER_DATASETS:+--datasets "\${COHORT_DESIGNER_DATASETS}"} \\
  \${COHORT_DESIGNER_PROVIDER:+--provider "\${COHORT_DESIGNER_PROVIDER}"} \\
  \${COHORT_DESIGNER_REGION:+--region "\${COHORT_DESIGNER_REGION}"}

# The host names the sandbox calls the server by, beside loopback.
cd "\${STATE}"
COHORT_DESIGNER_MODEL_KEY="\${COHORT_DESIGNER_MODEL_KEY:-none}" \\
  nohup "\${bin}" serve --config "\${STATE}/config.yaml" \\
  --state-dir "\${STATE}" --bind "\${BIND}" --port "\${PORT}" --allowed-host host.openshell.internal \\
  >> "\${LOGFILE}" 2>&1 &
echo "Started the cohort designer on \${BIND}:\${PORT}/mcp (model \${model}). Logs: \${LOGFILE}"
START

cat > "${INSTALL_DIR}/stop-server.sh" <<STOP
#!/bin/bash
# Stops the cohort designer and returns once it has exited, so a start-server.sh run straight
# after starts a new one: it starts nothing while the old process is still there. The designer
# closes its session on the way out, which takes a moment.
if ! pgrep -f "bin/cohort-designer serve --config" > /dev/null; then
  echo "The cohort designer is not running."
  exit 0
fi
pkill -f "bin/cohort-designer serve --config"
for _ in \$(seq 60); do
  if ! pgrep -f "bin/cohort-designer serve --config" > /dev/null; then
    echo "Stopped the cohort designer."
    exit 0
  fi
  sleep 0.5
done
echo "The cohort designer has not exited after 30 seconds; run this again before starting it." >&2
exit 1
STOP
chmod +x "${INSTALL_DIR}/start-server.sh" "${INSTALL_DIR}/stop-server.sh"
chmod -R a+rX "${INSTALL_DIR}"

echo "cohort-designer installed in ${INSTALL_DIR} (port ${DESIGNER_PORT}, bind ${DESIGNER_BIND_ADDRESS})"
echo "Done!"
