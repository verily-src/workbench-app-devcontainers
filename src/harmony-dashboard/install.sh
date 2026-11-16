#!/usr/bin/env bash
set -euo pipefail

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/harmony-dashboard"
ENV_FILE="/etc/harmony-dashboard.env"
START_SCRIPT="/usr/local/bin/start-harmony-dashboard.sh"

# Dev Container feature options are passed as uppercase env vars during build
DEFAULT_PORT="${PORT:-8502}"
DEFAULT_GCS_BUCKET="${GCSBUCKET:-anschutz-pancreatic-cancer-ds-bucket-wb-golden-parsnip-6065}"
DEFAULT_GCS_ROOT_PREFIX="${GCSROOTPREFIX:-experimental/run_artifacts}"
DEFAULT_DATASET_NAME="${DATASETNAME:-WP1 Data}"
DEFAULT_DATASET_SUBTITLE="${DATASETSUBTITLE:-Pancreatic Cancer Dataset | Agentic FHIR Harmonization}"
DEFAULT_LOCAL_PATH="${LOCALPATH:-}"

echo "Installing Harmony Dashboard into ${APP_DIR}..."

if ! python3 -m venv --help >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y && apt-get install -y --no-install-recommends python3-venv
  rm -rf /var/lib/apt/lists/*
fi

mkdir -p "${APP_DIR}"
cp "${FEATURE_DIR}/app.py" "${APP_DIR}/app.py"
cp "${FEATURE_DIR}/loader.py" "${APP_DIR}/loader.py"
cp "${FEATURE_DIR}/requirements.txt" "${APP_DIR}/requirements.txt"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --no-cache-dir --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --no-cache-dir -r "${APP_DIR}/requirements.txt"
chmod -R a+rX "${APP_DIR}"

cat <<EOF > "${ENV_FILE}"
DEFAULT_HARMONY_PORT="${DEFAULT_PORT}"
DEFAULT_GCS_BUCKET="${DEFAULT_GCS_BUCKET}"
DEFAULT_GCS_ROOT_PREFIX="${DEFAULT_GCS_ROOT_PREFIX}"
DEFAULT_HARMONY_DATASET_NAME="${DEFAULT_DATASET_NAME}"
DEFAULT_HARMONY_DATASET_SUBTITLE="${DEFAULT_DATASET_SUBTITLE}"
DEFAULT_HARMONY_LOCAL_PATH="${DEFAULT_LOCAL_PATH}"
EOF
chmod 644 "${ENV_FILE}"

cat <<'EOF' > "${START_SCRIPT}"
#!/usr/bin/env bash
set -euo pipefail

if [ -f /etc/harmony-dashboard.env ]; then
  # shellcheck disable=SC1091
  source /etc/harmony-dashboard.env
fi

PORT="${HARMONY_PORT:-${DEFAULT_HARMONY_PORT:-8502}}"
export GCS_BUCKET="${GCS_BUCKET:-${DEFAULT_GCS_BUCKET:-}}"
export GCS_ROOT_PREFIX="${GCS_ROOT_PREFIX:-${DEFAULT_GCS_ROOT_PREFIX:-}}"
export HARMONY_DATASET_NAME="${HARMONY_DATASET_NAME:-${DEFAULT_HARMONY_DATASET_NAME:-WP1 Data}}"
export HARMONY_DATASET_SUBTITLE="${HARMONY_DATASET_SUBTITLE:-${DEFAULT_HARMONY_DATASET_SUBTITLE:-}}"
export HARMONY_LOCAL_PATH="${HARMONY_LOCAL_PATH:-${DEFAULT_HARMONY_LOCAL_PATH:-}}"
export HARMONY_GCS_PATH="${HARMONY_GCS_PATH:-}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-}"

if pgrep -f "streamlit run /opt/harmony-dashboard/app.py" >/dev/null 2>&1; then
  echo "Harmony Dashboard is already running on port ${PORT}."
  exit 0
fi

echo "Starting Harmony Dashboard on port ${PORT}..."
nohup /opt/harmony-dashboard/.venv/bin/streamlit run /opt/harmony-dashboard/app.py \
  --server.address=0.0.0.0 \
  --server.port="${PORT}" \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false \
  >/tmp/harmony-dashboard.log 2>&1 &
EOF

chmod 755 "${START_SCRIPT}"
echo "Harmony Dashboard installation complete."