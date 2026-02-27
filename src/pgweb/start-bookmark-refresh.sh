#!/bin/bash
set -o errexit
set -o pipefail
set -o nounset

echo "Starting bookmark refresh for pgweb..."

# Create base directory (but not bookmarks subdirectory - that will be a symlink)
mkdir -p /root/.pgweb

# Make sure refresh script is executable
chmod +x /workspace/refresh-bookmarks.sh

# Run initial refresh (blocking) to populate bookmarks before app is marked ready
echo "Running initial bookmark refresh..."
/workspace/refresh-bookmarks.sh

# Start background loop for continuous refresh (detached from parent)
echo "Starting background bookmark refresh service (every 10 minutes)..."
# Single quotes intentional: $(date) should expand at runtime, not now
# shellcheck disable=SC2016
nohup bash -c '
  while true; do
    sleep 600  # 10 minutes
    /workspace/refresh-bookmarks.sh || echo "$(date): WARNING: Bookmark refresh failed"
  done
' >> /root/.pgweb/refresh.log 2>&1 &

REFRESH_PID=$!
echo "Bookmark refresh service configured (background PID: ${REFRESH_PID})"
