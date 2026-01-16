#!/bin/bash
# Script to download the notebook from the repository
# Run this in the container terminal: bash get-notebook.sh

NOTEBOOK_URL="https://raw.githubusercontent.com/SIVerilyDP/workbench-app-devcontainers/master/src/lab-results-analyzer/Lab_Results_Analysis.ipynb"
TARGET_DIR="/home/jovyan"
TARGET_FILE="${TARGET_DIR}/Lab_Results_Analysis.ipynb"

echo "Downloading notebook to ${TARGET_FILE}..."
curl -o "${TARGET_FILE}" "${NOTEBOOK_URL}"

if [ -f "${TARGET_FILE}" ]; then
    echo "✓ Notebook downloaded successfully!"
    echo "You can now find it at: ${TARGET_FILE}"
    ls -lh "${TARGET_FILE}"
else
    echo "✗ Failed to download notebook"
    exit 1
fi

