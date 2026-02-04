#!/bin/bash
set -e

echo "Starting bookmark refresh for pgweb..."

# Create bookmarks directory
mkdir -p /root/.pgweb/bookmarks

# Make sure refresh script is executable
chmod +x /workspace/refresh-bookmarks.sh

# Run initial refresh (blocking) to populate bookmarks before app is marked ready
echo "Running initial bookmark refresh..."
/workspace/refresh-bookmarks.sh

# Start background loop for continuous refresh
echo "Starting background bookmark refresh service (every 10 minutes)..."
(
  while true; do
    sleep 600  # 10 minutes
    /workspace/refresh-bookmarks.sh || echo "$(date): WARNING: Bookmark refresh failed"
  done
) &

echo "Bookmark refresh service configured (background PID: $!)"
