#!/bin/bash
set -e

BOOKMARK_DIR="/root/.pgweb/bookmarks"
REFRESH_INTERVAL=600  # 10 minutes (IAM tokens last 15 min)

# Create bookmark directory if it doesn't exist
mkdir -p "$BOOKMARK_DIR"

# Helper function to find workspace ID from UUID
get_workspace_id_from_uuid() {
  local uuid="$1"
  echo "$ALL_WORKSPACES" | jq -r --arg uuid "$uuid" '.[] | select(.uuid == $uuid) | .id'
}

# Recursively follow references using embedded referencedResource data
find_controlled_resource() {
  local resource_json="$1"
  local source_workspace_uuid="$2"

  local resource_type=$(echo "$resource_json" | jq -r '.resourceType')

  # If it's a controlled resource, return it and the workspace ID
  if [[ "$resource_type" == "AWS_AURORA_DATABASE" ]]; then
    # If we have a source workspace UUID, look up its ID
    if [[ -n "$source_workspace_uuid" && "$source_workspace_uuid" != "null" ]]; then
      local workspace_id=$(get_workspace_id_from_uuid "$source_workspace_uuid")
      if [[ -z "$workspace_id" ]]; then
        echo "ERROR: Could not find workspace ID for UUID: $source_workspace_uuid" >&2
        return 1
      fi
      echo "$workspace_id|$resource_json"
    else
      # Use current workspace
      echo "$CURRENT_WORKSPACE|$resource_json"
    fi
    return
  fi

  # If it's a reference, use the embedded referencedResource data
  if [[ "$resource_type" == "AWS_AURORA_DATABASE_REFERENCE" ]]; then
    local referenced_resource=$(echo "$resource_json" | jq -r '.referencedResource')

    if [[ -z "$referenced_resource" || "$referenced_resource" == "null" ]]; then
      echo "ERROR: Reference has no embedded referencedResource data" >&2
      return 1
    fi

    # Get the source workspace UUID - this is where the controlled resource lives
    local next_workspace_uuid=$(echo "$resource_json" | jq -r '.sourceWorkspaceId')

    # Recursively check the referenced resource, passing the workspace UUID
    find_controlled_resource "$referenced_resource" "$next_workspace_uuid"
    return
  fi

  # Unknown type
  echo "ERROR: Unknown resource type: $resource_type" >&2
  return 1
}

refresh_bookmarks() {
  echo "$(date): Refreshing pgweb bookmarks from Workbench resources..."

  # Get current workspace ID
  CURRENT_WORKSPACE=$(/usr/bin/wb workspace describe --format json | jq -r '.id')

  # Get list of all accessible workspaces for UUID->ID lookup
  ALL_WORKSPACES=$(/usr/bin/wb workspace list --format json)

  # Get list of Aurora databases from Workbench
  RESOURCES=$(/usr/bin/wb resource list --format json)

  # Clear old bookmarks
  rm -f "$BOOKMARK_DIR"/*.toml

  # Process each resource
  echo "$RESOURCES" | jq -c '.[]' | while read -r resource; do
    RESOURCE_TYPE=$(echo "$resource" | jq -r '.resourceType')

    # Skip non-Aurora resources
    if [[ ! "$RESOURCE_TYPE" =~ AURORA_DATABASE ]]; then
      continue
    fi

    RESOURCE_ID=$(echo "$resource" | jq -r '.id')
    echo "  Processing: $RESOURCE_ID (type: $RESOURCE_TYPE)"

    # Find the controlled resource by following reference chain
    if [[ "$RESOURCE_TYPE" == "AWS_AURORA_DATABASE_REFERENCE" ]]; then
      echo "    Following reference chain..."

      # Use embedded referencedResource data
      CONTROLLED_INFO=$(find_controlled_resource "$resource" "")
      CONTROLLED_WORKSPACE=$(echo "$CONTROLLED_INFO" | cut -d'|' -f1)
      DB_DATA=$(echo "$CONTROLLED_INFO" | cut -d'|' -f2-)
    else
      # Already a controlled resource
      CONTROLLED_WORKSPACE="$CURRENT_WORKSPACE"
      DB_DATA="$resource"
    fi

    echo "    Controlled resource workspace: $CONTROLLED_WORKSPACE"

    # For permissions, use credentials from the resource in the CURRENT workspace
    # Don't try to access the controlled workspace if it's a reference (may not have access)
    CAN_WRITE=false
    if [[ "$RESOURCE_TYPE" == "AWS_AURORA_DATABASE" ]]; then
      # Controlled resource - check workspace role
      WORKSPACE_INFO=$(/usr/bin/wb workspace describe --workspace "$CONTROLLED_WORKSPACE" --format json)
      HIGHEST_ROLE=$(echo "$WORKSPACE_INFO" | jq -r '.highestRole')
      echo "    User role in controlled workspace: $HIGHEST_ROLE"
      if [[ "$HIGHEST_ROLE" == "OWNER" || "$HIGHEST_ROLE" == "WRITER" ]]; then
        CAN_WRITE=true
      fi
    else
      # Referenced resource - try to get WRITE_READ credentials to check access
      echo "    Checking write access for referenced resource..."
      if /usr/bin/wb resource credentials --id "$RESOURCE_ID" --scope WRITE_READ --format json >/dev/null 2>&1; then
        CAN_WRITE=true
        echo "    User has write access to referenced resource"
      else
        echo "    User has read-only access to referenced resource"
      fi
    fi

    # Extract database info
    DB_NAME=$(echo "$DB_DATA" | jq -r '.databaseName')
    RW_ENDPOINT=$(echo "$DB_DATA" | jq -r '.rwEndpoint')
    RW_USER=$(echo "$DB_DATA" | jq -r '.rwUser')
    RO_ENDPOINT=$(echo "$DB_DATA" | jq -r '.roEndpoint')
    RO_USER=$(echo "$DB_DATA" | jq -r '.roUser')
    PORT=$(echo "$DB_DATA" | jq -r '.port')
    REGION=$(echo "$DB_DATA" | jq -r '.region // "us-east-1"')

    # Generate IAM token for RW user (only if user has write permissions)
    if [[ "$CAN_WRITE" == "true" && -n "$RW_ENDPOINT" && "$RW_ENDPOINT" != "null" ]]; then
      echo "    Getting Workbench credentials for RW access..."

      # Get temporary AWS credentials from Workbench
      WB_CREDS=$(/usr/bin/wb resource credentials --id "$RESOURCE_ID" --scope WRITE_READ --format json)
      AWS_ACCESS_KEY_ID=$(echo "$WB_CREDS" | jq -r '.AccessKeyId')
      AWS_SECRET_ACCESS_KEY=$(echo "$WB_CREDS" | jq -r '.SecretAccessKey')
      AWS_SESSION_TOKEN=$(echo "$WB_CREDS" | jq -r '.SessionToken')

      echo "    Generating RW token for $RW_USER@$RW_ENDPOINT..."
      # Generate RDS IAM auth token using those credentials
      RW_TOKEN=$(AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
                 AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
                 AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
                 aws rds generate-db-auth-token \
                   --hostname "$RW_ENDPOINT" \
                   --port "$PORT" \
                   --username "$RW_USER" \
                   --region "$REGION")

      # Create RW bookmark
      cat > "$BOOKMARK_DIR/${RESOURCE_ID} (Write-Read).toml" <<EOF
host = "$RW_ENDPOINT"
port = $PORT
user = "$RW_USER"
password = "$RW_TOKEN"
database = "$DB_NAME"
sslmode = "require"
EOF
      echo "    Created bookmark: ${RESOURCE_ID} (Write-Read)"
    elif [[ "$CAN_WRITE" == "false" ]]; then
      echo "    Skipping RW bookmark (user has read-only permissions)"
    fi

    # Generate IAM token for RO user (always create RO bookmark)
    if [[ -n "$RO_ENDPOINT" && "$RO_ENDPOINT" != "null" ]]; then
      echo "    Getting Workbench credentials for RO access..."

      # Get temporary AWS credentials from Workbench
      WB_CREDS=$(/usr/bin/wb resource credentials --id "$RESOURCE_ID" --scope READ_ONLY --format json)
      AWS_ACCESS_KEY_ID=$(echo "$WB_CREDS" | jq -r '.AccessKeyId')
      AWS_SECRET_ACCESS_KEY=$(echo "$WB_CREDS" | jq -r '.SecretAccessKey')
      AWS_SESSION_TOKEN=$(echo "$WB_CREDS" | jq -r '.SessionToken')

      echo "    Generating RO token for $RO_USER@$RO_ENDPOINT..."
      # Generate RDS IAM auth token using those credentials
      RO_TOKEN=$(AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
                 AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
                 AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
                 aws rds generate-db-auth-token \
                   --hostname "$RO_ENDPOINT" \
                   --port "$PORT" \
                   --username "$RO_USER" \
                   --region "$REGION")

      # Create RO bookmark
      cat > "$BOOKMARK_DIR/${RESOURCE_ID} (Read-Only).toml" <<EOF
host = "$RO_ENDPOINT"
port = $PORT
user = "$RO_USER"
password = "$RO_TOKEN"
database = "$DB_NAME"
sslmode = "require"
EOF
      echo "    Created bookmark: ${RESOURCE_ID} (Read-Only)"
    fi
  done

  BOOKMARK_COUNT=$(ls -1 "$BOOKMARK_DIR"/*.toml 2>/dev/null | wc -l)
  echo "$(date): Refresh complete. Created $BOOKMARK_COUNT bookmarks."

  # Write touchfile with refresh status
  cat > "$BOOKMARK_DIR/.last_refresh" <<EOF
timestamp=$(date -Iseconds)
bookmark_count=$BOOKMARK_COUNT
status=success
EOF
}

# Main loop
echo "Starting pgweb bookmark refresh service..."
echo "Bookmark directory: $BOOKMARK_DIR"
echo "Refresh interval: $REFRESH_INTERVAL seconds"

while true; do
  START_TIME=$(date +%s)

  if ! refresh_bookmarks; then
    echo "$(date): ERROR: Bookmark refresh failed"
    # Write error status to touchfile
    cat > "$BOOKMARK_DIR/.last_refresh" <<EOF
timestamp=$(date -Iseconds)
bookmark_count=0
status=failed
EOF
  fi

  # Calculate elapsed time and adjust sleep to maintain 10-minute cycle
  END_TIME=$(date +%s)
  ELAPSED=$((END_TIME - START_TIME))
  SLEEP_TIME=$((REFRESH_INTERVAL - ELAPSED))

  if [ $SLEEP_TIME -gt 0 ]; then
    echo "$(date): Refresh took ${ELAPSED}s. Sleeping for ${SLEEP_TIME}s to maintain ${REFRESH_INTERVAL}s cycle..."
    sleep "$SLEEP_TIME"
  else
    echo "$(date): WARNING: Refresh took ${ELAPSED}s, longer than ${REFRESH_INTERVAL}s interval!"
  fi
done
