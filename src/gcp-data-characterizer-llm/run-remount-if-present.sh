#!/bin/bash
# Run Workbench remount script only if it exists under /workspace.
set -e
if [ -f /workspace/startupscript/remount-on-restart.sh ]; then
  exec /workspace/startupscript/remount-on-restart.sh "$@"
else
  echo "Remount script not found, skipping."
  exit 0
fi
