#!/bin/bash
# Quick script to enable Vertex AI API and check setup

echo "=========================================="
echo "Vertex AI Setup Helper"
echo "=========================================="

# Get project ID
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: Could not get project ID"
    echo "   Run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo "📋 Project ID: $PROJECT_ID"
echo ""

# Step 1: Enable Vertex AI API
echo "🔧 Step 1: Enabling Vertex AI API..."
if gcloud services enable aiplatform.googleapis.com --project=$PROJECT_ID 2>/dev/null; then
    echo "✅ Vertex AI API enabled successfully!"
else
    echo "⚠️  Vertex AI API might already be enabled, or you don't have permissions"
fi

echo ""

# Step 2: Check IAM roles
echo "🔐 Step 2: Checking your IAM roles..."
ACCOUNT=$(gcloud config get-value account 2>/dev/null)
echo "   Account: $ACCOUNT"

ROLES=$(gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:$ACCOUNT" \
  --format="value(bindings.role)" 2>/dev/null)

if echo "$ROLES" | grep -q "aiplatform"; then
    echo "✅ You have Vertex AI roles:"
    echo "$ROLES" | grep "aiplatform"
else
    echo "⚠️  You may not have Vertex AI roles assigned"
    echo "   Required: roles/aiplatform.user or roles/aiplatform.admin"
    echo "   Contact your GCP administrator to assign the role"
fi

echo ""

# Step 3: Check available regions
echo "🌍 Step 3: Available Vertex AI regions:"
gcloud compute regions list --format="table(name)" 2>/dev/null | grep -E "(us-central|us-east|us-west|europe|asia)" | head -5

echo ""
echo "=========================================="
echo "✅ Setup check complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. If API wasn't enabled, wait a few minutes for it to activate"
echo "2. If you don't have roles, request them from your admin"
echo "3. Run: python test_vertex_ai_simple.py"
echo ""

