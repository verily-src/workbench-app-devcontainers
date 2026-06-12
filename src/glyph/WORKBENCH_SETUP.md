# Running Annotation Tool in Verily Workbench

## 🎯 Quick Start

### Option 1: Direct Upload (Fastest)

1. **Open Verily Workbench** in your browser
   - Go to: https://console.cloud.google.com/vertex-ai/workbench
   - Open your existing notebook instance or create one

2. **Upload the annotation tool**
   ```bash
   # In Workbench terminal, clone the repo
   cd ~
   git clone https://github.com/verily-src/verily1.git
   cd verily1
   git checkout rishabh-exp-glyph
   cd inhouse_annotation_tool
   ```

3. **Install dependencies**
   ```bash
   pip install Flask Werkzeug
   ```

4. **Setup your data**
   ```bash
   # Option A: Upload images via UI
   # Click Upload button → upload your cricket images to data/cricket_images/
   
   # Option B: Download from GCS
   gsutil cp gs://your-bucket/cricket-images/* ../data/cricket_images/
   ```

5. **Run the app**
   ```bash
   python app_demo.py
   ```

6. **Access the UI**
   - Click on the **port forwarding link** that Workbench shows
   - Or manually open: `https://[YOUR-NOTEBOOK-ID]-8080.notebooks.googleusercontent.com`

---

## 📓 Option 2: Using Jupyter Notebook

Create a new notebook (`annotation_tool.ipynb`):

### Cell 1: Setup
```python
# Install dependencies
!pip install Flask Werkzeug

# Navigate to tool directory
import os
os.chdir('/home/jupyter/verily1/inhouse_annotation_tool')
```

### Cell 2: Check images
```python
# List available images
!ls -lh ../data/cricket_images/
```

### Cell 3: Start server
```python
# Run in background
!python app_demo.py > /tmp/annotation.log 2>&1 &

# Wait for startup
import time
time.sleep(3)

# Check if running
!cat /tmp/annotation.log | tail -20
```

### Cell 4: Get access URL
```python
# Get the notebook proxy URL
import requests
import json

# Workbench proxy format
notebook_id = !gcloud notebooks instances describe [YOUR-INSTANCE-NAME] --location=[LOCATION] --format="value(name)"
proxy_url = f"https://{notebook_id[0]}-8080.notebooks.googleusercontent.com"

print(f"✓ Annotation tool running at:")
print(f"  {proxy_url}")
print(f"\n📝 Click the link to start annotating!")
```

---

## 🚀 Option 3: Production with BigQuery (Recommended)

### Step 1: Setup BigQuery Tables

```bash
# In Workbench terminal
cd ~/verily1/inhouse_annotation_tool

# Set your GCP project
export GCP_PROJECT_ID="your-verily-project-id"
export BQ_DATASET="cricket_annotations"
export GCS_BUCKET="your-cricket-images-bucket"

# Create tables
./setup_bigquery.sh
```

### Step 2: Upload Images to GCS

```bash
# Upload from local
gsutil cp /path/to/images/* gs://${GCS_BUCKET}/cricket/

# Or if images are in Workbench
gsutil cp ~/data/cricket_images/* gs://${GCS_BUCKET}/cricket/
```

### Step 3: Load Tasks to BigQuery

```bash
python scripts/load_tasks.py \
  --gcs-prefix gs://${GCS_BUCKET}/cricket/ \
  --project-id ${GCP_PROJECT_ID} \
  --dataset ${BQ_DATASET}
```

### Step 4: Run Production App

```bash
# Use production app (with BigQuery)
python app.py
```

---

## 🔧 Troubleshooting

### Port Already in Use

```bash
# Find and kill existing process
lsof -ti:8080 | xargs kill -9

# Or use a different port
PORT=8082 python app_demo.py
```

### Images Not Loading

```bash
# Check image directory exists
ls -la ../data/cricket_images/

# Check permissions
chmod 644 ../data/cricket_images/*
```

### Can't Access Web UI

**Method 1: Use Workbench Proxy**
```python
# In notebook cell
from IPython.display import HTML, display

port = 8080
proxy_url = f"/proxy/{port}/"

display(HTML(f'<a href="{proxy_url}" target="_blank">Open Annotation Tool</a>'))
```

**Method 2: Manual Port Forward**
```bash
# In your local terminal (not Workbench)
gcloud compute ssh [INSTANCE-NAME] \
  --project=[PROJECT] \
  --zone=[ZONE] \
  -- -L 8080:localhost:8080

# Then open: http://localhost:8080
```

### BigQuery Authentication

```bash
# Check authentication
gcloud auth list

# Authenticate if needed
gcloud auth application-default login
```

---

## 📊 Complete Workbench Setup Script

Save this as `setup_workbench.sh` in the annotation tool directory:

```bash
#!/bin/bash
# Complete setup script for Workbench

set -e

echo "🔧 Setting up Annotation Tool in Workbench"
echo "=========================================="

# 1. Install dependencies
echo "1. Installing dependencies..."
pip install -q Flask Werkzeug google-cloud-bigquery google-cloud-storage

# 2. Check for images
echo "2. Checking for images..."
IMAGE_DIR="../data/cricket_images"
if [ -d "$IMAGE_DIR" ] && [ "$(ls -A $IMAGE_DIR)" ]; then
    IMAGE_COUNT=$(ls -1 $IMAGE_DIR/*.{jpg,jpeg,png,gif} 2>/dev/null | wc -l)
    echo "   ✓ Found $IMAGE_COUNT images"
else
    echo "   ⚠️  No images found in $IMAGE_DIR"
    echo "   Upload images via Workbench UI or:"
    echo "   gsutil cp gs://your-bucket/* $IMAGE_DIR/"
    exit 1
fi

# 3. Choose mode
echo ""
echo "3. Choose mode:"
echo "   [1] Demo mode (local files, quick start)"
echo "   [2] Production mode (BigQuery + GCS)"
read -p "   Enter choice (1 or 2): " mode

if [ "$mode" == "1" ]; then
    # Demo mode
    echo ""
    echo "🚀 Starting demo server..."
    python app_demo.py &
    SERVER_PID=$!
    
    sleep 3
    
    echo ""
    echo "✓ Server started (PID: $SERVER_PID)"
    echo ""
    echo "Access the tool:"
    echo "  Workbench proxy: /proxy/8080/"
    echo "  Or click the port forwarding link in Workbench"
    echo ""
    echo "To stop: kill $SERVER_PID"
    
else
    # Production mode
    echo ""
    read -p "   GCP Project ID: " PROJECT_ID
    read -p "   GCS Bucket (without gs://): " GCS_BUCKET
    
    export GCP_PROJECT_ID=$PROJECT_ID
    export BQ_DATASET="cricket_annotations"
    export GCS_BUCKET=$GCS_BUCKET
    
    echo ""
    echo "Setting up BigQuery..."
    ./setup_bigquery.sh
    
    echo ""
    echo "Loading tasks from GCS..."
    python scripts/load_tasks.py \
      --gcs-prefix gs://${GCS_BUCKET}/cricket/ \
      --project-id ${PROJECT_ID} \
      --dataset ${BQ_DATASET}
    
    echo ""
    echo "🚀 Starting production server..."
    python app.py &
    SERVER_PID=$!
    
    sleep 3
    
    echo ""
    echo "✓ Production server started (PID: $SERVER_PID)"
    echo ""
    echo "Access the tool:"
    echo "  Workbench proxy: /proxy/8080/"
    echo ""
    echo "To stop: kill $SERVER_PID"
fi

echo ""
echo "=========================================="
echo "Setup complete! 🎉"
```

Make it executable:
```bash
chmod +x setup_workbench.sh
```

Run it:
```bash
./setup_workbench.sh
```

---

## 🎯 Quick Reference

### Start Demo Server
```bash
cd ~/verily1/inhouse_annotation_tool
python app_demo.py
```

### Access URLs
```
# Workbench proxy
https://[NOTEBOOK-ID]-8080.notebooks.googleusercontent.com

# Or use proxy path
/proxy/8080/
```

### Stop Server
```bash
# Find process
ps aux | grep app_demo.py

# Kill it
kill [PID]

# Or use pkill
pkill -f app_demo.py
```

### View Logs
```bash
# If running in background
tail -f /tmp/annotation_demo.log

# Or check Flask logs
cat /tmp/annotation.log
```

---

## 📱 Accessing from Jupyter

Add this cell to your notebook:

```python
from IPython.display import IFrame, display, HTML

# Display annotation tool inline
display(HTML(f'''
    <h3>Cricket Annotation Tool</h3>
    <iframe src="/proxy/8080/" width="100%" height="800px"></iframe>
'''))
```

Or as a link:

```python
from IPython.display import HTML, display

display(HTML('''
    <h2>🏏 Cricket Annotation Tool</h2>
    <a href="/proxy/8080/" target="_blank" style="
        display: inline-block;
        padding: 15px 30px;
        background: #3498db;
        color: white;
        text-decoration: none;
        border-radius: 5px;
        font-size: 18px;
    ">Open Annotation Tool →</a>
'''))
```

---

## 🔐 Authentication

Workbench handles authentication automatically via:
- IAM user credentials
- Service account (for BigQuery/GCS)
- No additional setup needed!

---

## 💡 Pro Tips

1. **Use tmux/screen** for persistent sessions:
   ```bash
   tmux new -s annotation
   python app_demo.py
   # Ctrl+B, then D to detach
   # tmux attach -t annotation to reattach
   ```

2. **Auto-restart on crash**:
   ```bash
   while true; do python app_demo.py; sleep 5; done
   ```

3. **Check resources**:
   ```bash
   # Memory usage
   free -h
   
   # Disk space
   df -h
   
   # Running processes
   htop
   ```

4. **Save annotations periodically**:
   ```bash
   # Export every hour (in cron)
   0 * * * * curl http://localhost:8080/api/export > ~/annotations_backup.json
   ```

---

## 🎉 You're Ready!

The annotation tool should now be running in your Verily Workbench. Access it via the proxy URL and start annotating! 🏏
