

# Deployment Guide - In-House Annotation Tool

## Overview

Deploy a lightweight annotation tool that replaces Label Studio using Google Cloud infrastructure.

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────┐
│         Users (Annotators in Browser)               │
└────────────────────┬────────────────────────────────┘
                     │ HTTPS
                     ↓
┌─────────────────────────────────────────────────────┐
│    Workbench / Cloud Run / App Engine               │
│                                                      │
│    Flask Web App (app.py)                           │
│    - Serves HTML/JS UI                              │
│    - Fetches tasks from BigQuery                    │
│    - Generates GCS signed URLs                      │
│    - Saves annotations to BigQuery                  │
└────────┬──────────────────────┬─────────────────────┘
         │                      │
         ↓                      ↓
┌──────────────────┐   ┌──────────────────┐
│    BigQuery      │   │   GCS Bucket     │
│  - Tasks table   │   │  - Images        │
│  - Annotations   │   │                  │
└──────────────────┘   └──────────────────┘
```

---

## Deployment Options

### Option 1: Workbench (Quickest for Testing)

**Best for**: Development, internal testing, small teams

```bash
# 1. Open Vertex AI Workbench
# 2. Clone this repo or upload files
# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
export GCP_PROJECT_ID="your-project-id"
export BQ_DATASET="cricket_annotations"
export GCS_BUCKET="cricket-images"

# 5. Setup BigQuery
./setup_bigquery.sh

# 6. Run the app
python app.py

# Access at: http://localhost:8080
# Or use port forwarding if remote
```

**Pros**: Fast setup, good for development  
**Cons**: Single user, not highly available, manual management

---

### Option 2: Cloud Run (Recommended for Production)

**Best for**: Production, multiple users, auto-scaling

```bash
# 1. Set project
gcloud config set project YOUR_PROJECT_ID

# 2. Setup BigQuery
./setup_bigquery.sh

# 3. Deploy to Cloud Run
gcloud run deploy cricket-annotation-tool \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars GCP_PROJECT_ID=YOUR_PROJECT_ID,BQ_DATASET=cricket_annotations,GCS_BUCKET=cricket-images \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 10

# 4. Get the URL
gcloud run services describe cricket-annotation-tool --region us-central1 --format 'value(status.url)'
```

**Pros**: Auto-scaling, serverless, HTTPS included, IAM auth  
**Cons**: Cold starts (negligible for this use case)

**Cost**: ~$5-20/month for moderate usage (first 2M requests free)

---

### Option 3: App Engine (Alternative Production)

**Best for**: Simple deployment, integrated with Google services

```bash
# 1. Create app.yaml
cat > app.yaml << EOF
runtime: python311
entrypoint: gunicorn -b :$PORT app:app

env_variables:
  GCP_PROJECT_ID: "your-project-id"
  BQ_DATASET: "cricket_annotations"
  GCS_BUCKET: "cricket-images"

automatic_scaling:
  target_cpu_utilization: 0.65
  min_instances: 1
  max_instances: 10
EOF

# 2. Deploy
gcloud app deploy
```

**Pros**: Simple, integrated, stable URLs  
**Cons**: Less flexible than Cloud Run

---

## Step-by-Step Setup

### 1. Prerequisites

```bash
# Install gcloud CLI
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login
gcloud auth application-default login

# Set project
gcloud config set project YOUR_PROJECT_ID
```

### 2. Setup BigQuery

```bash
# Run setup script
export GCP_PROJECT_ID="your-project-id"
export BQ_DATASET="cricket_annotations"
./setup_bigquery.sh

# Verify tables created
bq ls $BQ_DATASET
```

### 3. Upload Images to GCS

```bash
# Create bucket
gsutil mb -l us-central1 gs://your-cricket-images/

# Upload images
gsutil -m cp -r /path/to/cricket/images/* gs://your-cricket-images/
```

### 4. Load Annotation Tasks

**Option A: From GCS bucket**
```bash
python scripts/load_tasks.py \
  --gcs-prefix gs://your-cricket-images/ \
  --project-id your-project-id \
  --dataset cricket_annotations
```

**Option B: From CSV**
```bash
# Create tasks.csv
cat > tasks.csv << EOF
image_gcs_path,task_type,labels
gs://your-bucket/image1.jpg,bbox,"Batting,Bowling,Fielding,Wicketkeeping"
gs://your-bucket/image2.jpg,bbox,"Batting,Bowling,Fielding,Wicketkeeping"
EOF

python scripts/load_tasks.py \
  --csv tasks.csv \
  --project-id your-project-id \
  --dataset cricket_annotations
```

### 5. Deploy Application

Choose one of the deployment options above.

### 6. Access the Tool

- **Workbench**: http://localhost:8080
- **Cloud Run**: https://cricket-annotation-tool-xxxxx.run.app
- **App Engine**: https://YOUR_PROJECT_ID.appspot.com

---

## Usage Workflow

### For Annotators

1. **Open the web app** in browser
2. **Click "Load Tasks"** to see pending tasks
3. **Click a task** to start annotating
4. **Select a label** (Batting, Bowling, etc.)
5. **Draw bounding boxes** on the image
6. **Click Submit** when done
7. Annotation automatically saved to BigQuery!

### For ML Engineers

```bash
# Export annotations to COCO format
python scripts/export_annotations.py \
  --format coco \
  --output annotations_coco.json \
  --project-id your-project-id \
  --dataset cricket_annotations

# Use annotations for training
# The COCO file is now ready for YOLO, Detectron2, etc.
```

---

## Security & Access Control

### IAM Permissions

Grant annotators minimal permissions:

```bash
# Service account for the app
gcloud iam service-accounts create annotation-tool-sa \
  --display-name "Annotation Tool Service Account"

# Grant permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member serviceAccount:annotation-tool-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role roles/bigquery.dataEditor

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member serviceAccount:annotation-tool-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --role roles/storage.objectViewer
```

### Authentication

**For Cloud Run:**
```bash
# Require authentication
gcloud run services update cricket-annotation-tool \
  --region us-central1 \
  --no-allow-unauthenticated

# Grant access to specific users
gcloud run services add-iam-policy-binding cricket-annotation-tool \
  --region us-central1 \
  --member user:annotator@example.com \
  --role roles/run.invoker
```

---

## Monitoring & Maintenance

### View Logs

```bash
# Cloud Run logs
gcloud run services logs read cricket-annotation-tool \
  --region us-central1 \
  --limit 50

# Or in Cloud Console
# https://console.cloud.google.com/logs
```

### Check Task Status

```sql
-- In BigQuery Console
SELECT
  status,
  COUNT(*) as count
FROM `your-project.cricket_annotations.annotation_tasks`
GROUP BY status;
```

### Monitor Costs

```bash
# BigQuery usage
bq ls --project_id YOUR_PROJECT_ID --max_results 10

# GCS usage
gsutil du -sh gs://your-cricket-images/

# Cloud Run metrics
# https://console.cloud.google.com/run
```

---

## Comparison: In-House vs Label Studio

| Feature | In-House Tool | Label Studio |
|---------|---------------|--------------|
| **Cost** | ~$10/month | ~$500/month (managed) or self-host complexity |
| **Setup Time** | 30 minutes | 2-4 hours |
| **Customization** | Full control | Limited unless Enterprise |
| **GCP Integration** | Native (BQ + GCS) | Requires connectors |
| **Scalability** | Auto-scales with Cloud Run | Requires k8s setup |
| **Maintenance** | Minimal | Moderate (updates, backups) |
| **Features** | Bbox, classification | More advanced (NER, segmentation) |

**Recommendation**: Use in-house tool for simple bbox/classification. Use Label Studio for complex annotations (segmentation, NER, etc.)

---

## Troubleshooting

### Images not loading

```bash
# Check GCS permissions
gsutil ls gs://your-bucket/

# Verify signed URL generation
# Check app.py logs for errors
```

### BigQuery errors

```bash
# Verify tables exist
bq ls $BQ_DATASET

# Check permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID
```

### App won't start

```bash
# Check environment variables
echo $GCP_PROJECT_ID
echo $BQ_DATASET

# Test locally first
python app.py
```

---

## Cost Estimate

**For 10,000 images annotated over 1 month:**

- **BigQuery**: <$1 (queries + storage)
- **GCS**: ~$2 (100GB images)
- **Cloud Run**: ~$5-10 (compute)
- **Total**: **~$10-15/month**

Compare to Label Studio managed: **~$500/month**

**Savings: 97%** 🎉

---

## Next Steps

1. **Deploy** using one of the options above
2. **Load tasks** from your GCS bucket
3. **Start annotating** via the web UI
4. **Export** annotations to COCO/CSV for ML training
5. **Iterate** and improve based on usage

---

## Support

For issues:
1. Check logs in Cloud Console
2. Verify BigQuery tables and data
3. Test GCS signed URLs
4. Review app.py for errors

Good luck with your annotation project! 🏏
