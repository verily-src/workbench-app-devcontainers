# Quick Start - 5 Minutes to Running Annotation Tool

## 🚀 Fastest Path (Local Testing)

```bash
# 1. Navigate to tool directory
cd inhouse_annotation_tool

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment (replace with your values)
export GCP_PROJECT_ID="your-project-id"
export BQ_DATASET="cricket_annotations"
export GCS_BUCKET="your-bucket"

# 4. Setup BigQuery tables
./setup_bigquery.sh

# 5. Upload test images to GCS
gsutil cp /path/to/images/* gs://your-bucket/cricket/

# 6. Load annotation tasks
python scripts/load_tasks.py \
  --gcs-prefix gs://your-bucket/cricket/ \
  --project-id your-project-id \
  --dataset cricket_annotations

# 7. Run the app
python app.py

# 8. Open browser
open http://localhost:8080
```

---

## 📝 What You'll See

### Landing Page
```
🏏 Cricket Annotation Tool
┌─────────────────────────────────────────────┐
│ Pending: 10 | Completed: 0 | Total: 10      │
└─────────────────────────────────────────────┘

Tasks                    Image Canvas          Annotations
┌──────────┐            ┌──────────┐          ┌──────────┐
│ task_001 │            │          │          │ 1. Batting│
│ task_002 │            │  [Image] │          │ 2. Bowling│
│ task_003 │            │          │          │          │
└──────────┘            └──────────┘          └──────────┘
                        
                        [Labels: Batting | Bowling | ...]
                        [Undo] [Clear] [Submit]
```

### Annotation Flow

1. Click "Load Tasks" → See 10 pending tasks
2. Click a task → Image loads in center
3. Click "Batting" label
4. Draw box around batter
5. Click "Bowling" label
6. Draw box around bowler
7. Click "Submit"
8. ✓ Saved to BigQuery!
9. Next task loads automatically

---

## 🎯 Sample Data

Create a test dataset:

```bash
# Create sample task CSV
cat > sample_tasks.csv << 'EOF'
image_gcs_path,task_type,labels
gs://cricket-images/dhoni.png,bbox,"Batting,Bowling,Fielding,Wicketkeeping"
gs://cricket-images/virat.png,bbox,"Batting,Bowling,Fielding,Wicketkeeping"
gs://cricket-images/bumrah.png,bbox,"Batting,Bowling,Fielding,Wicketkeeping"
EOF

# Load to BigQuery
python scripts/load_tasks.py --csv sample_tasks.csv
```

---

## 🔍 Verify It's Working

### Check BigQuery

```bash
# View tasks
bq query "SELECT task_id, status, image_gcs_path FROM cricket_annotations.annotation_tasks LIMIT 5"

# View annotations
bq query "SELECT annotation_id, task_id, annotator FROM cricket_annotations.annotations LIMIT 5"
```

### Check via API

```bash
# Get pending tasks
curl http://localhost:8080/api/tasks?limit=5 | jq

# Get stats
curl http://localhost:8080/api/stats | jq
```

---

## 📊 Export Annotations

After annotating a few images:

```bash
# Export to COCO format
python scripts/export_annotations.py \
  --format coco \
  --output annotations.json

# Export to CSV
python scripts/export_annotations.py \
  --format csv \
  --output annotations.csv

# View results
cat annotations.json | jq '.annotations | length'
```

---

## 🎨 Features to Try

### Keyboard Shortcuts
- `1-5` - Quick label selection
- `z` - Undo last box
- `Enter` - Submit annotation

### UI Features
- Click and drag to draw boxes
- Zoom/pan on images (Fabric.js controls)
- Edit/delete existing boxes
- Progress tracking (stats at top)

---

## 🐛 Troubleshooting

### "No tasks found"
```bash
# Check if tasks loaded
bq query "SELECT COUNT(*) FROM cricket_annotations.annotation_tasks"

# If 0, re-run load script
python scripts/load_tasks.py --gcs-prefix gs://your-bucket/
```

### "Image not loading"
```bash
# Verify GCS path
gsutil ls gs://your-bucket/

# Check permissions
gcloud auth application-default print-access-token
```

### "BigQuery errors"
```bash
# Verify dataset exists
bq ls | grep cricket_annotations

# Re-run setup
./setup_bigquery.sh
```

---

## ⚡ Production Deployment

Once testing works locally:

```bash
# Deploy to Cloud Run (5 minutes)
gcloud run deploy cricket-annotation-tool \
  --source . \
  --region us-central1 \
  --set-env-vars GCP_PROJECT_ID=$GCP_PROJECT_ID,BQ_DATASET=$BQ_DATASET

# Get URL
gcloud run services describe cricket-annotation-tool \
  --region us-central1 \
  --format 'value(status.url)'
```

---

## 📈 Next Steps

1. ✅ **Annotate** some images
2. ✅ **Export** to COCO format
3. ✅ **Train** a YOLO model
4. ✅ **Deploy** the detection model
5. ✅ **Automate** future annotations!

---

## File Structure Recap

```
inhouse_annotation_tool/
├── app.py                      # Flask backend
├── requirements.txt            # Dependencies
├── Dockerfile                  # Container image
├── setup_bigquery.sh          # BQ setup script
│
├── templates/
│   └── index.html             # Web UI
│
├── static/
│   ├── js/
│   │   └── annotator.js       # Annotation logic
│   └── css/
│       └── style.css          # Styling
│
├── scripts/
│   ├── load_tasks.py          # Load tasks to BQ
│   └── export_annotations.py  # Export from BQ
│
├── README.md                   # Overview
├── DEPLOYMENT_GUIDE.md        # Full deployment docs
└── QUICKSTART.md              # This file
```

---

You're all set! Start annotating! 🏏🎯
