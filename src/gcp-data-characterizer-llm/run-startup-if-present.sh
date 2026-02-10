#!/bin/bash
# Run Workbench startup script only if it exists (when full repo is mounted at /workspace).
# If only the app folder is mounted, skip so the container can still start.
set -e
# postCreateCommand runs with workspaceFolder = /workspace
if [ -f /workspace/startupscript/post-startup.sh ]; then
  exec /workspace/startupscript/post-startup.sh "$@"
else
  echo "Startup script not found (startupscript/ not under /workspace), skipping."
  exit 0
fi
