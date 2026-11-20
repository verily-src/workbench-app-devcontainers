#!/usr/bin/env bash

# install.sh installs NVIDIA Kumo Relational and the forecast MCP server (README.md).

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
readonly FORECAST_PORT="${PORT:-"9244"}"
readonly FORECAST_BIND_ADDRESS="${BINDADDRESS:-"127.0.0.1"}"
readonly ROLE="${ROLE:-"app"}"
readonly PYTHON_VERSION="3.12"
readonly UV_VERSION="0.9.7"
# pyg-lib, the sampler's backend, is built per torch version (requirements.txt pins both).
readonly PYG_INDEX="https://data.pyg.org/whl/torch-2.13.0+cpu.html"
readonly WEIGHTS_REPO="nvidia/Kumo-Relational"

# Kept out of the user's home: a large tree in the code-server workspace (/config) sets the
# editor's Python extension searching it and the workspace's bucket mounts, which overloads the app.
readonly INSTALL_DIR="/opt/kumo-forecast"
readonly SANDBOX_DIR="/opt/agent-sandbox"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

case "${ROLE}" in
    app|broker) ;;
    *) echo "Error: role must be app or broker, got '${ROLE}'."; exit 1 ;;
esac

# The catalog the sandbox's policy is rendered from. agent-sandbox reads every file here.
mkdir -p "${SANDBOX_DIR}/mcp.d"
install -m 644 "${FEATURE_DIR}/sandbox/forecast.yaml" "${SANDBOX_DIR}/mcp.d/forecast.yaml"
if [[ "${ROLE}" == broker ]]; then
    echo "kumo-forecast: catalog installed in ${SANDBOX_DIR}/mcp.d (role broker)"
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
if ! command -v curl > /dev/null 2>&1; then
    apt-get update -y
    apt-get -y install --no-install-recommends ca-certificates curl
    rm -rf /var/lib/apt/lists/*
fi

mkdir -p "${INSTALL_DIR}/bin"
curl --retry 3 -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-$(uname -m)-unknown-linux-gnu.tar.gz" |
    tar -xz --strip-components=1 -C "${INSTALL_DIR}/bin"
export UV_PYTHON_INSTALL_DIR="${INSTALL_DIR}/python" UV_CACHE_DIR="/tmp/uv-cache" UV_LINK_MODE=copy
"${INSTALL_DIR}/bin/uv" venv --python "${PYTHON_VERSION}" "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/bin/uv" pip install --python "${INSTALL_DIR}/venv/bin/python" \
    --find-links "${PYG_INDEX}" -r "${FEATURE_DIR}/requirements.txt"
rm -rf /tmp/uv-cache

# The model's weights, fetched now: the server runs offline (HF_HUB_OFFLINE) from this cache.
# They are fetched by building the model once, online, so the cache holds the revision the
# package pins (refs/v1.0.1 for 0.2.1); a snapshot of the repository's default revision does not
# satisfy it offline, which fails the app's image build.
HF_HUB_CACHE="${INSTALL_DIR}/hf" "${INSTALL_DIR}/venv/bin/python" -W ignore -c \
    'import sdm; sdm.models.KumoRelational(device="cpu"); print("kumo-forecast: weights cached")'
test -d "${INSTALL_DIR}/hf/models--${WEIGHTS_REPO/\//--}"

rm -rf "${INSTALL_DIR}/kumo_forecast"
mkdir -p "${INSTALL_DIR}/kumo_forecast"
install -m 644 "${FEATURE_DIR}"/kumo_forecast/*.py "${INSTALL_DIR}/kumo_forecast/"
cp "${FEATURE_DIR}/serve.py" "${INSTALL_DIR}/"
PYTHONPATH="${INSTALL_DIR}" HF_HUB_CACHE="${INSTALL_DIR}/hf" HF_HUB_OFFLINE=1 "${INSTALL_DIR}/venv/bin/python" -W ignore -c \
    'import sdm, pyg_lib, fastmcp, kumo_forecast.service, kumo_forecast.model; sdm.models.KumoRelational(device="cpu"); print("kumo-forecast: imports and weights ok")'

cat > "${INSTALL_DIR}/start-server.sh" <<START
#!/bin/bash
# Starts the forecast MCP server as a background daemon, as the app's user: it reads BigQuery
# with that user's Application Default Credentials and the cohort designer's sessions from its
# state folder. Settings: KUMO_FORECAST_BIND, KUMO_FORECAST_PORT, KUMO_FORECAST_SESSIONS (default
# ~/.cohort-designer/sessions), KUMO_FORECAST_GPU_GB (the model's GPU memory cap, default 5),
# KUMO_FORECAST_CONTEXT (labeled histories in context, default 3000), KUMO_FORECAST_ESTIMATORS
# (default 4), KUMO_FORECAST_MAX_ROWS (the most rows of tables a forecast reads, default 50,000,000),
# KUMO_FORECAST_BILLING_PROJECT, KUMO_FORECAST_SMALL_CELL (default 20; 0 shows every count).

set -o errexit
set -o nounset
set -o pipefail

readonly DIR="${INSTALL_DIR}"
readonly STATE="\${KUMO_FORECAST_STATE:-\${HOME}/.kumo-forecast}"
readonly SESSIONS="\${KUMO_FORECAST_SESSIONS:-\${HOME}/.cohort-designer/sessions}"
readonly PORT="\${KUMO_FORECAST_PORT:-${FORECAST_PORT}}"
readonly BIND="\${KUMO_FORECAST_BIND:-${FORECAST_BIND_ADDRESS}}"
readonly LOGFILE="\${STATE}/server.log"

if pgrep -f "\${DIR}/serve.py" > /dev/null; then
  echo "The Kumo forecast server is already running."
  exit 0
fi
mkdir -p "\${STATE}" "\${SESSIONS}" && chmod 700 "\${STATE}"

cd "\${STATE}"
PYTHONPATH="\${DIR}" HF_HUB_CACHE="\${DIR}/hf" HF_HUB_OFFLINE=1 \\
  nohup "\${DIR}/venv/bin/python" -W ignore "\${DIR}/serve.py" --sessions-dir "\${SESSIONS}" \\
  --state-dir "\${STATE}" --bind "\${BIND}" --port "\${PORT}" --allowed-host host.openshell.internal \\
  >> "\${LOGFILE}" 2>&1 &
echo "Started the Kumo forecast server on \${BIND}:\${PORT}/mcp. Logs: \${LOGFILE}"
START

cat > "${INSTALL_DIR}/stop-server.sh" <<STOP
#!/bin/bash
# Stops the forecast server and returns once it has exited.
if ! pgrep -f "${INSTALL_DIR}/serve.py" > /dev/null; then
  echo "The Kumo forecast server is not running."
  exit 0
fi
pkill -f "${INSTALL_DIR}/serve.py"
for _ in \$(seq 60); do
  if ! pgrep -f "${INSTALL_DIR}/serve.py" > /dev/null; then
    echo "Stopped the Kumo forecast server."
    exit 0
  fi
  sleep 0.5
done
echo "The Kumo forecast server has not exited after 30 seconds; run this again." >&2
exit 1
STOP
chmod +x "${INSTALL_DIR}/start-server.sh" "${INSTALL_DIR}/stop-server.sh" "${INSTALL_DIR}/serve.py"
chmod -R a+rX "${INSTALL_DIR}"

echo "kumo-forecast installed in ${INSTALL_DIR} (port ${FORECAST_PORT}, bind ${FORECAST_BIND_ADDRESS})"
echo "Done!"
