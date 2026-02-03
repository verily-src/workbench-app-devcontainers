#!/bin/bash
set -e

echo "Starting pgweb with auto-refreshing IAM bookmarks..."

# Create bookmarks directory
mkdir -p /root/.pgweb/bookmarks

# Wait for Workbench CLI to be installed, authenticated, and workspace set (postCreateCommand completes)
# This ensures wb is installed, configured, authenticated, and workspace is set
echo "Waiting for Workbench CLI initialization..."
while ! /usr/bin/wb auth status >/dev/null 2>&1; do
  sleep 2
done
echo "Authenticated, waiting for workspace to be set..."
while ! /usr/bin/wb workspace describe --format json >/dev/null 2>&1; do
  sleep 2
done
echo "Workbench CLI is ready!"

# Make sure refresh script is executable
chmod +x /workspace/refresh-bookmarks.sh

# Start bookmark refresher in background
echo "Starting bookmark refresh service..."
/workspace/refresh-bookmarks.sh &

# Wait for initial refresh to complete (up to 5 minutes)
echo "Waiting for initial bookmark discovery..."
WAIT_COUNT=0
while [ ! -f /root/.pgweb/bookmarks/.last_refresh ] && [ $WAIT_COUNT -lt 300 ]; do
  sleep 2
  WAIT_COUNT=$((WAIT_COUNT + 2))
done

if [ -f /root/.pgweb/bookmarks/.last_refresh ]; then
  # Show refresh status
  source /root/.pgweb/bookmarks/.last_refresh
  echo "Initial refresh complete: $bookmark_count bookmark(s) created at $timestamp"
else
  echo "WARNING: Initial refresh did not complete within 5 minutes"
fi

# Start pgweb in foreground (keeps container alive)
echo "Starting pgweb server on port 8081..."
exec pgweb --sessions --bind=0.0.0.0 --listen=8081 --bookmarks-dir=/root/.pgweb/bookmarks
