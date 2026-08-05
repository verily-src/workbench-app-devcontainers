#!/bin/bash
# Configure Gemini CLI for Violet AI Assistant

set -e

USER_NAME="${1:-app}"
USER_HOME="${2:-/home/app}"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"

echo "Configuring Gemini CLI for user ${USER_NAME}..."

# Create .gemini directory
sudo -u "${USER_NAME}" mkdir -p "${USER_HOME}/.gemini"

# Update settings.json - merge with existing if present
SETTINGS_FILE="${USER_HOME}/.gemini/settings.json"

if [ -f "${SETTINGS_FILE}" ]; then
    # Merge auth settings into existing file using jq
    TMP_FILE=$(mktemp)
    jq --arg project "${PROJECT_ID}" \
       '. + {
         "auth": {"method": "vertexai"},
         "project": $project,
         "location": "us-central1",
         "model": "gemini-2.5-flash"
       }' "${SETTINGS_FILE}" > "${TMP_FILE}"
    mv "${TMP_FILE}" "${SETTINGS_FILE}"
else
    # Create new settings.json
    cat > "${SETTINGS_FILE}" << EOF
{
  "auth": {
    "method": "vertexai"
  },
  "project": "${PROJECT_ID}",
  "location": "us-central1",
  "model": "gemini-2.5-flash"
}
EOF
fi

chown "${USER_NAME}:${USER_NAME}" "${SETTINGS_FILE}"

# Add Gemini environment variables to .bashrc if not already present
if ! grep -q "GOOGLE_GENAI_USE_VERTEXAI" "${USER_HOME}/.bashrc"; then
    cat >> "${USER_HOME}/.bashrc" << 'EOF'

# Gemini CLI configuration for Violet
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_LOCATION=us-central1
export GEMINI_CLI_TRUST_WORKSPACE=true
EOF
    echo "Added Gemini environment variables to .bashrc"
fi

echo "Gemini CLI configured successfully!"
