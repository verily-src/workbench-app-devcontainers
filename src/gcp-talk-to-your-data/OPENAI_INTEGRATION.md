# OpenAI API Integration Guide

## Overview

This guide explains how to integrate OpenAI API with your Workbench custom app using Google Cloud Secret Manager.

## What Needs to Be Done

### 1. **Permissions Setup** ✅ (Already Done by IT)
- Secret created: `projects/wb-smart-cabbage-5940/secrets/si-ops-openai-api-key/versions/latest`
- Access group: `si-ops-openai-key-accessors`
- **Action Required**: Ensure your Workbench app's service account has access to this secret

### 2. **Install Required Packages**
The app needs to install:
- `google-cloud-secret-manager` - To access the secret
- `openai` - To use OpenAI API

### 3. **Code Integration**
- Add function to retrieve secret from GCP Secret Manager
- Initialize OpenAI client with the secret
- Integrate OpenAI into data analysis workflow

### 4. **Service Account Permissions**
The Workbench app's service account needs:
- `secretmanager.secrets.get` permission on the secret
- Or membership in `si-ops-openai-key-accessors` group

---

## Step-by-Step Integration

### Step 1: Verify Service Account Access

The Workbench app runs with a service account. You need to ensure this service account can access the secret.

**Option A**: Add service account to the access group
- Add the service account email to `si-ops-openai-key-accessors` group

**Option B**: Grant direct IAM permission
- Grant `Secret Manager Secret Accessor` role to the service account on the secret

### Step 2: Update the App Code

The code has been updated to:
1. Auto-install `google-cloud-secret-manager` and `openai`
2. Retrieve the secret from GCP Secret Manager
3. Initialize OpenAI client
4. Provide helper functions for OpenAI integration

### Step 3: Use OpenAI in Your Analysis

You can now use OpenAI to:
- Generate natural language summaries of data
- Answer questions about the data
- Create custom visualizations based on prompts
- Generate insights and recommendations

---

## Secret Path Configuration

Based on your IT team's setup:

```python
PROJECT_ID = "wb-smart-cabbage-5940"
SECRET_NAME = "si-ops-openai-api-key"
SECRET_VERSION = "latest"  # or "live" depending on your setup
SECRET_PATH = f"projects/{PROJECT_ID}/secrets/{SECRET_NAME}/versions/{SECRET_VERSION}"
```

---

## Usage Example

```python
from google.cloud import secretmanager
import openai

# Get secret
secret_client = secretmanager.SecretManagerServiceClient()
openai_key = secret_client.access_secret_version(name=SECRET_PATH).payload.data.decode("UTF-8")

# Initialize OpenAI client
client = openai.OpenAI(
    api_key=openai_key,
    base_url="https://us.api.openai.com/v1/",
)

# Use OpenAI
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a data analyst."},
        {"role": "user", "content": "Analyze this data: ..."}
    ]
)
```

---

## Troubleshooting

### Error: Permission Denied
- **Cause**: Service account doesn't have access to secret
- **Fix**: Add service account to `si-ops-openai-key-accessors` group or grant IAM permission

### Error: Secret Not Found
- **Cause**: Wrong project ID or secret name
- **Fix**: Verify the secret path matches exactly

### Error: Module Not Found
- **Cause**: Packages not installed
- **Fix**: The app auto-installs packages, but you can manually run:
  ```bash
  pip install google-cloud-secret-manager openai
  ```

---

## Security Best Practices

1. ✅ **Never hardcode API keys** - Always use Secret Manager
2. ✅ **Use service accounts** - Don't use personal credentials
3. ✅ **Limit access** - Only grant access to necessary service accounts
4. ✅ **Monitor usage** - Track API calls and costs
5. ✅ **Rotate keys** - Update secrets regularly

---

## Next Steps

1. Verify service account has access to the secret
2. Update the app code (already done in the updated files)
3. Test the integration in your Workbench app
4. Use OpenAI features in your data analysis workflow

