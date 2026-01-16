#!/bin/bash
# Script to copy notebook to home directory for easy access
# This runs as part of postCreateCommand

set -e

NOTEBOOK_SOURCE="/workspace/Lab_Results_Analysis.ipynb"
NOTEBOOK_TARGET="/home/jovyan/Lab_Results_Analysis.ipynb"
USER_HOME="/home/jovyan"

# If notebook exists in workspace, copy it to home directory
if [ -f "$NOTEBOOK_SOURCE" ]; then
    echo "Copying notebook from workspace to home directory..."
    cp "$NOTEBOOK_SOURCE" "$NOTEBOOK_TARGET"
    chown jovyan:users "$NOTEBOOK_TARGET"
    echo "✓ Notebook copied to $NOTEBOOK_TARGET"
# Otherwise, download it from the repository
elif [ ! -f "$NOTEBOOK_TARGET" ]; then
    echo "Notebook not found in workspace, downloading from repository..."
    curl -s -o "$NOTEBOOK_TARGET" \
        "https://raw.githubusercontent.com/SIVerilyDP/workbench-app-devcontainers/master/src/lab-results-analyzer/Lab_Results_Analysis.ipynb"
    chown jovyan:users "$NOTEBOOK_TARGET"
    echo "✓ Notebook downloaded to $NOTEBOOK_TARGET"
fi

# Ensure proper permissions
chmod 644 "$NOTEBOOK_TARGET"

echo "Notebook is ready at: $NOTEBOOK_TARGET"

