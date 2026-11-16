#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8502}"
APP_DIR="/opt/harmony-dashboard"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv python3-pip
rm -rf /var/lib/apt/lists/*

mkdir -p "${APP_DIR}"
cp "${SCRIPT_DIR}/app.py" "${APP_DIR}/app.py"
cp "${SCRIPT_DIR}/loader.py" "${APP_DIR}/loader.py"
cp "${SCRIPT_DIR}/requirements.txt" "${APP_DIR}/requirements.txt"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --no-cache-dir --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --no-cache-dir -r "${APP_DIR}/requirements.txt"

cat <<EOF > /usr/local/bin/start-harmony-dashboard.sh
#!/usr/bin/env bash
set -euo pipefail

LISTEN_PORT="\${HARMONY_PORT:-${PORT}}"
LOG_DIR="/var/log/workbench"
mkdir -p "\${LOG_DIR}"

if pgrep -f "streamlit run ${APP_DIR}/app.py" >/dev/null 2>&1; then
  exit 0
fi

nohup "${APP_DIR}/.venv/bin/streamlit" run "${APP_DIR}/app.py" \
  --server.address=0.0.0.0 \
  --server.port="\${LISTEN_PORT}" \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false \
  > "\${LOG_DIR}/harmony-dashboard.log" 2>&1 &
EOF

chmod +x /usr/local/bin/start-harmony-dashboard.sh