#!/bin/bash
set -o errexit
set -o pipefail

# Allow overriding via environment for local testing
readonly WB_EXE="${WB_EXE:-/usr/bin/wb}"
readonly PGWEB_BASE="${PGWEB_BASE:-/root/.pgweb}"
readonly BOOKMARK_DIR="${PGWEB_BASE}/bookmarks"

# Create base directory if it doesn't exist
mkdir -p "${PGWEB_BASE}"

# Helper function to get credentials and generate IAM auth token
generate_iam_token() {
  local resource_id="${1}"
  local scope="${2}"
  local endpoint="${3}"
  local port="${4}"
  local username="${5}"
  local region="${6}"

  # Get credentials from Workbench
  local wb_creds
  wb_creds=$(${WB_EXE} resource credentials --id "${resource_id}" --scope "${scope}" --format json 2>/dev/null) || return 1
  readonly wb_creds

  # Extract AWS credentials
  local access_key secret_key session_token
  access_key=$(echo "${wb_creds}" | jq -r '.AccessKeyId')
  secret_key=$(echo "${wb_creds}" | jq -r '.SecretAccessKey')
  session_token=$(echo "${wb_creds}" | jq -r '.SessionToken')
  readonly access_key secret_key session_token

  # Generate IAM token
  AWS_ACCESS_KEY_ID="${access_key}" \
  AWS_SECRET_ACCESS_KEY="${secret_key}" \
  AWS_SESSION_TOKEN="${session_token}" \
  aws rds generate-db-auth-token \
    --hostname "${endpoint}" \
    --port "${port}" \
    --username "${username}" \
    --region "${region}"
}

# Helper function to create bookmark TOML file
create_bookmark() {
  local output_file="${1}"
  local endpoint="${2}"
  local port="${3}"
  local username="${4}"
  local password="${5}"
  local database="${6}"

  cat > "${output_file}" <<EOF
host = "${endpoint}"
port = ${port}
user = "${username}"
password = "${password}"
database = "${database}"
sslmode = "require"
EOF
}

refresh_bookmarks() {
  echo "$(date): Refreshing pgweb bookmarks from Workbench resources..."

  # Create temporary directory for new bookmarks (using PID for uniqueness)
  local TEMP_DIR="${PGWEB_BASE}/bookmarks.tmp.$$"
  readonly TEMP_DIR
  rm -rf "${TEMP_DIR}"
  mkdir -p "${TEMP_DIR}"

  # Get list of Aurora databases from Workbench
  local RESOURCES
  RESOURCES=$(${WB_EXE} resource list --format json)
  readonly RESOURCES

  # Process each resource
  echo "${RESOURCES}" | jq -c '.[]' | while read -r resource; do
    local RESOURCE_TYPE
    RESOURCE_TYPE=$(echo "${resource}" | jq -r '.resourceType')

    # Skip non-Aurora resources
    if [[ ! "${RESOURCE_TYPE}" =~ AURORA_DATABASE ]]; then
      continue
    fi

    local RESOURCE_ID
    RESOURCE_ID=$(echo "${resource}" | jq -r '.id')
    echo "  Processing: ${RESOURCE_ID} (type: ${RESOURCE_TYPE})"

    # Extract database details from top level (controlled) or referencedResource (reference)
    local DB_DATA
    if [[ "${RESOURCE_TYPE}" == "AWS_AURORA_DATABASE" ]]; then
      DB_DATA="${resource}"
    else
      DB_DATA=$(echo "${resource}" | jq -r '.referencedResource')
    fi

    # Extract database connection info
    local DB_NAME RO_ENDPOINT RO_USER RW_ENDPOINT RW_USER PORT REGION
    DB_NAME=$(echo "${DB_DATA}" | jq -r '.databaseName')
    RO_ENDPOINT=$(echo "${DB_DATA}" | jq -r '.roEndpoint')
    RO_USER=$(echo "${DB_DATA}" | jq -r '.roUser')
    RW_ENDPOINT=$(echo "${DB_DATA}" | jq -r '.rwEndpoint')
    RW_USER=$(echo "${DB_DATA}" | jq -r '.rwUser')
    PORT=$(echo "${DB_DATA}" | jq -r '.port')
    REGION=$(echo "${DB_DATA}" | jq -r '.region // "us-east-1"')

    # Validate all required fields are present
    if [[ -z "${DB_NAME}" || "${DB_NAME}" == "null" ]] || \
       [[ -z "${RO_ENDPOINT}" || "${RO_ENDPOINT}" == "null" ]] || \
       [[ -z "${RO_USER}" || "${RO_USER}" == "null" ]] || \
       [[ -z "${RW_ENDPOINT}" || "${RW_ENDPOINT}" == "null" ]] || \
       [[ -z "${RW_USER}" || "${RW_USER}" == "null" ]] || \
       [[ -z "${PORT}" || "${PORT}" == "null" ]]; then
      echo "    Missing required database fields, skipping"
      continue
    fi

    # Try to create READ_ONLY bookmark
    echo "    Checking read access..."
    local RO_TOKEN
    if RO_TOKEN=$(generate_iam_token "${RESOURCE_ID}" "READ_ONLY" "${RO_ENDPOINT}" "${PORT}" "${RO_USER}" "${REGION}"); then
      echo "    Read access confirmed"
      echo "    Creating read-only bookmark..."
      create_bookmark "${TEMP_DIR}/${RESOURCE_ID} (Read-Only).toml" "${RO_ENDPOINT}" "${PORT}" "${RO_USER}" "${RO_TOKEN}" "${DB_NAME}"
      echo "    Created bookmark: ${RESOURCE_ID} (Read-Only)"
    else
      echo "    No read access to ${RESOURCE_ID}, skipping"
      continue
    fi

    # Try to create WRITE_READ bookmark
    echo "    Checking write access..."
    local RW_TOKEN
    if RW_TOKEN=$(generate_iam_token "${RESOURCE_ID}" "WRITE_READ" "${RW_ENDPOINT}" "${PORT}" "${RW_USER}" "${REGION}"); then
      echo "    Write access confirmed"
      echo "    Creating write-read bookmark..."
      create_bookmark "${TEMP_DIR}/${RESOURCE_ID} (Write-Read).toml" "${RW_ENDPOINT}" "${PORT}" "${RW_USER}" "${RW_TOKEN}" "${DB_NAME}"
      echo "    Created bookmark: ${RESOURCE_ID} (Write-Read)"
    else
      echo "    No write access, skipping write-read bookmark"
    fi
  done

  # Count bookmarks - must use find since the while loop runs in a subshell (due to pipe),
  # so a counter variable incremented in the loop would not be visible here
  local BOOKMARK_COUNT
  BOOKMARK_COUNT=$(find "${TEMP_DIR}" -name "*.toml" -type f 2>/dev/null | wc -l)
  readonly BOOKMARK_COUNT
  echo "$(date): Refresh complete. Created ${BOOKMARK_COUNT} bookmarks."

  # Atomically update symlink to point to new bookmark directory
  ln -sfn "$(basename "${TEMP_DIR}")" "${BOOKMARK_DIR}"

  # Cleanup old bookmark directories (all except current)
  find "${PGWEB_BASE}" -maxdepth 1 -type d -name "bookmarks.tmp.*" ! -name "bookmarks.tmp.$$" -exec rm -rf {} \;
}

# Run single refresh
if ! refresh_bookmarks; then
  echo "$(date): ERROR: Bookmark refresh failed"
  exit 1
fi
