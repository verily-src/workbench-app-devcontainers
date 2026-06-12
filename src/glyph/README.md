# In-House Annotation Tool

## Overview

A lightweight annotation tool for Google Cloud that replaces Label Studio.

**Stack:**
- **Data Source**: BigQuery (tasks table)
- **Storage**: Google Cloud Storage (images)
- **Backend**: Flask (Python)
- **Frontend**: HTML/JS with Fabric.js for annotations
- **Output**: BigQuery (annotations table)
- **Hosting**: Workbench / Cloud Run / App Engine

## Architecture

```
BQ Tasks → Flask API → Web UI → BQ Annotations
              ↓
           GCS Images
```

## Setup

### 1. BigQuery Tables

```sql
-- Tasks table
CREATE TABLE `project.dataset.annotation_tasks` (
  task_id STRING NOT NULL,
  image_gcs_path STRING NOT NULL,
  task_type STRING NOT NULL,  -- 'bbox', 'classification', etc.
  labels ARRAY<STRING>,
  metadata JSON,
  status STRING DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  assigned_to STRING
);

-- Annotations table
CREATE TABLE `project.dataset.annotations` (
  annotation_id STRING NOT NULL,
  task_id STRING NOT NULL,
  annotator STRING NOT NULL,
  annotation_data JSON,  -- Flexible schema for different annotation types
  annotation_type STRING,  -- 'bbox', 'classification', etc.
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
```

### 2. Environment Variables

```bash
export GCP_PROJECT_ID="your-project-id"
export BQ_DATASET="your-dataset"
export GCS_BUCKET="your-bucket"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the App

```bash
python app.py
# Or for development:
flask run --debug
```

## Usage

1. **Load tasks into BQ** (see `scripts/load_tasks.py`)
2. **Start the web app** (`python app.py`)
3. **Annotators access** the web UI
4. **Annotations save** automatically to BQ
5. **Export annotations** from BQ for ML training

## Features

- ✅ Bounding box annotation
- ✅ Classification labels
- ✅ Multi-label support
- ✅ Image zoom/pan
- ✅ Undo/redo
- ✅ Keyboard shortcuts
- ✅ Auto-save to BigQuery
- ✅ Task queue management
- ✅ Progress tracking

## Deployment

### Workbench
```bash
# Run directly in Jupyter notebook
!python app.py
```

### Cloud Run
```bash
gcloud run deploy annotation-tool \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

### App Engine
```bash
gcloud app deploy
```

## File Structure

```
inhouse_annotation_tool/
├── app.py                 # Flask backend
├── requirements.txt       # Python dependencies
├── static/
│   ├── js/
│   │   └── annotator.js  # Annotation logic
│   └── css/
│       └── style.css     # Styling
├── templates/
│   └── index.html        # Main UI
├── scripts/
│   ├── load_tasks.py     # Upload tasks to BQ
│   └── export_annotations.py  # Export from BQ
└── README.md
```

## Cost Estimate

- **BigQuery**: ~$5/TB queried (minimal for small datasets)
- **GCS**: ~$0.02/GB/month storage
- **Cloud Run**: Free tier covers most use cases
- **Total**: <$20/month for moderate usage

Much cheaper than Label Studio hosting + management!
