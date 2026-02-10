# Requesting Gemini/Generative AI Access

Since you don't have access to Gemini models, here's what to request from your GCP administrator:

## Request Template

```
Subject: Request Access to Vertex AI Generative AI (Gemini Models)

Hi [Admin Name],

I need access to Vertex AI Generative AI models (Gemini) in project [PROJECT_ID: wb-blazing-melon-1175].

Could you please:

1. Enable the Generative AI API:
   - API name: generativelanguage.googleapis.com
   - Or: aiplatform.googleapis.com (if not already enabled)

2. Grant me access to Gemini models:
   - IAM role: roles/aiplatform.user (if not already assigned)
   - Or: roles/ml.developer

3. Enable Vertex AI Generative AI features:
   - This may require enabling specific model access in the project

I'm trying to use Gemini models for data analysis tasks in Workbench.

Thank you!
```

## Alternative: Use Fallback Version

While waiting for access, you can use the fallback version that works without LLM:

```bash
python llm_data_chat_fallback.py
```

This uses rule-based pattern matching to answer common questions about your data.

## What APIs Need to Be Enabled

1. **Generative Language API** (`generativelanguage.googleapis.com`)
   - Required for Gemini models
   
2. **Vertex AI API** (`aiplatform.googleapis.com`)
   - Already enabled (you confirmed this works)

## Check Current Status

```bash
# Check enabled APIs
gcloud services list --enabled --project=wb-blazing-melon-1175 | grep -E "(generativelanguage|aiplatform)"

# Check your roles
gcloud projects get-iam-policy wb-blazing-melon-1175 \
  --flatten="bindings[].members" \
  --filter="bindings.members:$(gcloud config get-value account)" \
  --format="table(bindings.role)"
```

