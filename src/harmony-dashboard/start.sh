#!/usr/bin/env bash
set -euo pipefail

LISTEN_PORT="${HARMONY_PORT:-8502}"
LOG_DIR="/var/log/workbench"
mkdir -p "${LOG_DIR}" 2>/dev/null || true

if pgrep -f "streamlit run /app/app.py" >/dev/null 2>&1; then
  exit 0
fi

nohup /opt/harmony-venv/bin/streamlit run /app/app.py \
  --server.address=0.0.0.0 \
  --server.port="${LISTEN_PORT}" \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false \
  > "${LOG_DIR}/harmony-dashboard.log" 2>&1 &
