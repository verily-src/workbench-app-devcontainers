# Requesting API Access (For Non-Project Owners)

## Option 1: Ask Project Administrator

Send this request to your GCP project administrator or owner:

```
Subject: Request to Enable Vertex AI API

Hi [Admin Name],

I need access to Vertex AI services in project [PROJECT_ID: 1093873783908].

Could you please:
1. Enable the Service Usage API
2. Enable the Vertex AI API  
3. Assign me the "Vertex AI User" role (roles/aiplatform.user)

This will allow me to use Vertex AI services from Workbench.

Thank you!
```

## Option 2: Check if APIs Are Already Enabled

The APIs might already be enabled by someone else. Test it:

```bash
# In Workbench terminal
python check_vertex_ai_without_permissions.py
```

This will check if Vertex AI is accessible without requiring enable permissions.

## Option 3: Use a Different Project

If you have access to another GCP project where you have more permissions:

```bash
# List available projects
gcloud projects list

# Switch to a different project
gcloud config set project YOUR_OTHER_PROJECT_ID

# Then enable APIs there
gcloud services enable aiplatform.googleapis.com
```

## Option 4: Check What You Can Access

See what Vertex AI resources already exist (if any):

```python
from google.cloud import aiplatform
from google.auth import default

creds, project = default()
aiplatform.init(project=project, location="us-central1")

# Try to list existing resources (read-only, might work)
try:
    models = aiplatform.Model.list()
    print(f"Found {len(list(models))} models")
except Exception as e:
    print(f"Cannot list models: {e}")
```

## Option 5: Use Vertex AI via REST API

If you have read permissions, you might be able to use Vertex AI via REST API:

```python
from google.auth import default
import requests

credentials, project = default()
credentials.refresh(requests.Request())

# Example: List models via REST
url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/us-central1/models"
headers = {"Authorization": f"Bearer {credentials.token}"}
response = requests.get(url, headers=headers)
print(response.json())
```

## Quick Check Commands

```bash
# Check if APIs are enabled (read-only check)
gcloud services list --enabled --project=1093873783908 | grep -E "(serviceusage|aiplatform)"

# Check your current roles
gcloud projects get-iam-policy 1093873783908 \
  --flatten="bindings[].members" \
  --filter="bindings.members:$(gcloud config get-value account)" \
  --format="table(bindings.role)"
```

