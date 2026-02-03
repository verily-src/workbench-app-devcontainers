#!/bin/bash
set -e

echo "Starting pgweb with auto-refreshing IAM bookmarks..."

# Create bookmarks directory with proper permissions
mkdir -p /home/pgweb/.pgweb/bookmarks
chown -R pgweb:pgweb /home/pgweb/.pgweb

# Make sure refresh script is executable
chmod +x /workspace/refresh-bookmarks.sh

# Start bookmark refresher in background
echo "Starting bookmark refresh service..."
/workspace/refresh-bookmarks.sh &

# Give it a moment to create initial bookmarks
sleep 2

# Start pgweb in foreground (keeps container alive)
echo "Starting pgweb server on port 8081..."
exec pgweb --sessions --bind=0.0.0.0 --listen=8081
