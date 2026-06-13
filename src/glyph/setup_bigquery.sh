#!/bin/bash
# Setup BigQuery tables for annotation tool

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
DATASET="${BQ_DATASET:-image_annotations}"
LOCATION="${BQ_LOCATION:-US}"

echo "🔧 Setting up BigQuery for Annotation Tool"
echo "Project: $PROJECT_ID"
echo "Dataset: $DATASET"
echo "Location: $LOCATION"
echo ""

# Create dataset
echo "1. Creating dataset..."
bq --location=$LOCATION mk --dataset \
    --description "Glyph annotation tasks and results" \
    $PROJECT_ID:$DATASET \
    || echo "Dataset already exists"

# Create tasks table
echo "2. Creating annotation_tasks table..."
bq mk --table \
    $PROJECT_ID:$DATASET.annotation_tasks \
    task_id:STRING,image_gcs_path:STRING,task_type:STRING,labels:STRING,metadata:STRING,status:STRING,created_at:TIMESTAMP,assigned_to:STRING \
    || echo "Table already exists"

# Create annotations table
echo "3. Creating annotations table..."
bq mk --table \
    $PROJECT_ID:$DATASET.annotations \
    annotation_id:STRING,task_id:STRING,annotator:STRING,annotation_data:STRING,annotation_type:STRING,created_at:TIMESTAMP,updated_at:TIMESTAMP \
    || echo "Table already exists"

echo ""
echo "✓ BigQuery setup complete!"
echo ""
echo "Tables created:"
echo "  - $PROJECT_ID:$DATASET.annotation_tasks"
echo "  - $PROJECT_ID:$DATASET.annotations"
echo ""
echo "Next steps:"
echo "  1. Upload images to GCS: gsutil cp images/* gs://your-bucket/"
echo "  2. Load tasks: python scripts/load_tasks.py --gcs-prefix gs://your-bucket/"
echo "  3. Start app: python app.py"
