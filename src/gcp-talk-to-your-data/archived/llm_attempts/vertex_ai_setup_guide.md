# Vertex AI Setup Guide for Workbench

## Step 1: Enable Vertex AI API

### Option A: Via GCP Console (Web UI)
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. Navigate to **APIs & Services** → **Library**
4. Search for "Vertex AI API"
5. Click on it and press **Enable**

### Option B: Via gcloud CLI (in Workbench terminal)
```bash
# Get your project ID first
gcloud config get-value project

# Enable Vertex AI API
gcloud services enable aiplatform.googleapis.com

# Verify it's enabled
gcloud services list --enabled | grep aiplatform
```

## Step 2: Check/Assign IAM Roles

### Check Your Current Roles
```bash
# In Workbench terminal
gcloud projects get-iam-policy $(gcloud config get-value project) \
  --flatten="bindings[].members" \
  --filter="bindings.members:$(gcloud config get-value account)" \
  --format="table(bindings.role)"
```

### Required Roles
You need one of these roles:
- `roles/aiplatform.user` (Vertex AI User) - **Recommended for most users**
- `roles/aiplatform.admin` (Vertex AI Admin) - Full access

### If You Need to Request Access
Contact your GCP administrator or project owner to assign the role:
- They can assign it via: **IAM & Admin** → **IAM** in GCP Console
- Or via command: `gcloud projects add-iam-policy-binding PROJECT_ID --member="user:YOUR_EMAIL" --role="roles/aiplatform.user"`

## Step 3: Verify/Set Your Region

### Check Available Regions
```bash
# List available Vertex AI regions
gcloud compute regions list | grep -E "(us-central|us-east|us-west|europe|asia)"
```

### Common Regions
- `us-central1` (Iowa) - Most common, best availability
- `us-east1` (South Carolina)
- `us-west1` (Oregon)
- `europe-west1` (Belgium)
- `asia-east1` (Taiwan)

### Set Region in Your Scripts
Update the region in your test scripts:
```python
region = "us-central1"  # Change this to your preferred region
aiplatform.init(project=project_id, location=region)
```

## Step 4: Test Again After Setup

After completing steps 1-3, run the test again:

```bash
python test_vertex_ai_simple.py
```

You should now see all green checkmarks! ✅

## Step 5: Use Vertex AI in Your Scripts

### Basic Example: List Models
```python
from google.cloud import aiplatform

# Initialize
aiplatform.init(project="YOUR_PROJECT_ID", location="us-central1")

# List models (if you have any)
models = aiplatform.Model.list()
for model in models:
    print(f"Model: {model.display_name}")
```

### Example: Use Vertex AI for Predictions
```python
from google.cloud import aiplatform
from google.cloud.aiplatform import prediction

# Initialize
aiplatform.init(project="YOUR_PROJECT_ID", location="us-central1")

# Use a deployed model endpoint
endpoint = aiplatform.Endpoint("YOUR_ENDPOINT_ID")
predictions = endpoint.predict(instances=[{"feature1": value1, "feature2": value2}])
```

## Troubleshooting

### "API not enabled" error
→ Complete Step 1 above

### "Permission denied" error
→ Complete Step 2 above (request IAM role)

### "Location not found" error
→ Complete Step 3 above (verify region)

### Still having issues?
Check the full test output:
```bash
python test_vertex_ai.py
```

