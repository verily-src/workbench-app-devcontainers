#!/bin/bash
# WB Data Catalog — Startup Script

echo "Starting WB Data Catalog..."

GEMINI_MODEL="${GEMINI_MODEL:-}"
CHAT_MODEL="${CHAT_MODEL:-}"

if [ -z "$GCP_PROJECT_ID" ]; then
    GCP_PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/project/project-id" 2>/dev/null || echo "")
fi

if [ -z "$GCP_PROJECT_ID" ]; then
    echo "WARNING: No GCP_PROJECT_ID detected. Configure via the UI at http://localhost:8080"
fi

# DATA_PROJECT_ID defaults to GCP_PROJECT_ID if not set
DATA_PROJECT_ID="${DATA_PROJECT_ID:-$GCP_PROJECT_ID}"

echo "   Billing Project:  ${GCP_PROJECT_ID:-<not set>}"
echo "   Data Project:     ${DATA_PROJECT_ID:-<not set>}"
echo "   Gemini Model:     ${GEMINI_MODEL:-<auto-detect>}"
echo "   Chat Model:       ${CHAT_MODEL:-<default>}"
echo "   Port:             8080"
echo ""

export GCP_PROJECT_ID
export DATA_PROJECT_ID
export GEMINI_MODEL
export CHAT_MODEL

exec uvicorn main:app --host 0.0.0.0 --port 8080
