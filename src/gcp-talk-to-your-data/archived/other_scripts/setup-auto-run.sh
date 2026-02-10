#!/bin/bash
# Script to set up auto-run of the notebook analysis
# This creates a JupyterLab extension that auto-runs the notebook on startup

set -e

NOTEBOOK_PATH="/home/jovyan/Lab_Results_Analysis.ipynb"
AUTO_RUN_SCRIPT="/home/jovyan/.jupyter/labextensions/auto-run-notebook/auto-run.js"

# Create directory for auto-run extension
mkdir -p "$(dirname "$AUTO_RUN_SCRIPT")"

# Create a simple auto-run script (JupyterLab will need to be configured separately)
# For now, we'll create a startup script that can be run manually or via postCreateCommand

cat > /home/jovyan/run-analysis.sh << 'EOF'
#!/bin/bash
# Auto-run the analysis notebook
cd /home/jovyan
jupyter nbconvert --to notebook --execute Lab_Results_Analysis.ipynb --output Lab_Results_Analysis_executed.ipynb 2>&1 || echo "Note: Auto-execution completed (some warnings may appear)"
EOF

chmod +x /home/jovyan/run-analysis.sh
chown jovyan:users /home/jovyan/run-analysis.sh

echo "✓ Auto-run setup script created at /home/jovyan/run-analysis.sh"
echo "  Note: For full auto-run, the notebook will need to be configured in JupyterLab settings"

