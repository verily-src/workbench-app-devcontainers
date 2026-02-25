#!/bin/bash

# create-cortex-config.sh
#
# Creates cortex.yaml configuration file in the container user's home directory
# This script runs inside the container and attempts to retrieve GCP metadata

set -o errexit
set -o nounset
set -o pipefail

# Wait for metadata server to be ready
echo "Waiting 5 seconds for metadata server to be ready..."
sleep 5

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <home-directory>"
  exit 1
fi

readonly HOME_DIR="${1}"
readonly CORTEX_CONFIG_PATH="${HOME_DIR}/cortex.yaml"

echo "Creating cortex.yaml configuration..."

# Try to get GCP project ID from metadata server
# Note: This may not work from inside the container depending on network configuration
GCP_PROJECT_ID=""
GCP_REGION=""

if GCP_PROJECT_ID=$(curl --retry 3 --max-time 5 -s -f \
  -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/project/project-id" 2>/dev/null); then
  echo "Successfully retrieved GCP project ID: ${GCP_PROJECT_ID}"

  # Also try to get the region
  if ZONE=$(curl --retry 3 --max-time 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" 2>/dev/null); then
    GCP_REGION=$(echo "${ZONE}" | awk -F'/' '{print $4}' | sed 's/-[^-]*$//')
    echo "Successfully retrieved GCP region: ${GCP_REGION}"
  fi
else
  echo "Warning: Could not retrieve GCP project ID from metadata server"
  echo "The metadata server may not be accessible from inside the container"

  # Check if gcloud is available and authenticated as a fallback
  if command -v gcloud &> /dev/null; then
    if GCP_PROJECT_ID=$(gcloud config get-value project 2>/dev/null) && [[ -n "${GCP_PROJECT_ID}" ]]; then
      echo "Retrieved project ID from gcloud config: ${GCP_PROJECT_ID}"
      GCP_REGION=$(gcloud config get-value compute/region 2>/dev/null || echo "")
    fi
  fi
fi

# Create the cortex.yaml file
if [[ -n "${GCP_PROJECT_ID}" ]]; then
  cat > "${CORTEX_CONFIG_PATH}" << EOF
# Cortex configuration
# Generated on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
gcp_project_id: ${GCP_PROJECT_ID}
gcp_region: ${GCP_REGION:-UNKNOWN}
profiles_repo: shared-artifacts-a2hhlz
EOF

  echo "cortex.yaml created successfully at ${CORTEX_CONFIG_PATH}"
  cat "${CORTEX_CONFIG_PATH}"
else
  echo "Warning: Could not determine GCP project ID"
  echo "Creating cortex.yaml with placeholder values"
  cat > "${CORTEX_CONFIG_PATH}" << EOF
# Cortex configuration
# Generated on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# WARNING: Could not automatically determine GCP project ID
gcp_project_id: "UNKNOWN"
gcp_region: "UNKNOWN"
profiles_repo: shared-artifacts-a2hhlz
# Please update this file with the correct values
EOF
  echo "cortex.yaml created with placeholder at ${CORTEX_CONFIG_PATH}"
fi

# Ensure proper ownership
if [[ -f "${CORTEX_CONFIG_PATH}" ]]; then
  chmod 644 "${CORTEX_CONFIG_PATH}"
fi
