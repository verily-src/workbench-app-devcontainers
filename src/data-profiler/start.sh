#!/bin/bash
# WB Data Profiler — Startup Script

echo "Starting WB Data Profiler..."

OUTPUT_GCS_BUCKET="${OUTPUT_GCS_BUCKET:-}"
GEMINI_MODEL="${GEMINI_MODEL:-}"

if [ -z "$GCP_PROJECT_ID" ]; then
    GCP_PROJECT_ID=$(curl -s -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/project/project-id" 2>/dev/null || echo "")
fi

if [ -z "$GCP_PROJECT_ID" ]; then
    echo "WARNING: No GCP_PROJECT_ID detected. BQ and LLM features will not work."
fi

CMD="python app.py --port=8080"

if [ -n "$GCP_PROJECT_ID" ]; then
    CMD="${CMD} --project=${GCP_PROJECT_ID}"
fi

if [ -n "$DATA_PROJECT_IDS" ]; then
    CMD="${CMD} --data-project ${DATA_PROJECT_IDS}"
fi

if [ -n "$OUTPUT_GCS_BUCKET" ]; then
    CMD="${CMD} --output-bucket=${OUTPUT_GCS_BUCKET}"
fi

if [ -n "$GEMINI_MODEL" ]; then
    CMD="${CMD} --model=${GEMINI_MODEL}"
fi

echo "   Project:        ${GCP_PROJECT_ID:-<not set>}"
echo "   Data Projects:  ${DATA_PROJECT_IDS:-<not set>}"
echo "   Output Bucket:  ${OUTPUT_GCS_BUCKET:-<not set>}"
echo "   Gemini Model:   ${GEMINI_MODEL:-<auto-detect>}"
echo "   Port:           8080"
echo ""
echo "Running: ${CMD}"
echo ""

exec ${CMD}
