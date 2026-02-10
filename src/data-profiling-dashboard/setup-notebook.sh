#!/bin/bash
# Copy app files to Jupyter home so they appear in the file browser and run correctly.
# Runs as part of postCreateCommand.

set -e

USER_HOME="/home/jovyan"
REPO_RAW="https://raw.githubusercontent.com/SIVerilyDP/workbench-app-devcontainers/master/src/data-profiling-dashboard"

# Notebook
if [ -f "/workspace/Lab_Results_Analysis.ipynb" ]; then
    cp "/workspace/Lab_Results_Analysis.ipynb" "$USER_HOME/Lab_Results_Analysis.ipynb"
    echo "✓ Notebook copied to $USER_HOME"
else
    curl -s -o "$USER_HOME/Lab_Results_Analysis.ipynb" "$REPO_RAW/Lab_Results_Analysis.ipynb"
    echo "✓ Notebook downloaded to $USER_HOME"
fi

# Profiling script (run from terminal or double-click)
if [ -f "/workspace/run_data_profiling.py" ]; then
    cp "/workspace/run_data_profiling.py" "$USER_HOME/run_data_profiling.py"
    echo "✓ run_data_profiling.py copied to $USER_HOME"
fi

chown -R jovyan:users "$USER_HOME/Lab_Results_Analysis.ipynb" "$USER_HOME/run_data_profiling.py" 2>/dev/null || true
chmod 644 "$USER_HOME/Lab_Results_Analysis.ipynb" "$USER_HOME/run_data_profiling.py" 2>/dev/null || true
echo "Data Profiling Dashboard files are ready in $USER_HOME"
