#!/usr/bin/env python3
"""
Vertex AI Usage Examples
Now that Vertex AI is accessible, here are examples of what you can do.
"""

import sys
import subprocess

print("="*70)
print("🚀 Vertex AI Usage Examples")
print("="*70)

# Install packages if needed
try:
    from google.cloud import aiplatform
    from google.auth import default
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-aiplatform"])
    from google.cloud import aiplatform
    from google.auth import default

# Initialize
credentials, project_id = default()
region = "us-central1"  # Change if needed

print(f"\n📋 Project: {project_id}")
print(f"🌍 Region: {region}")

aiplatform.init(project=project_id, location=region)
print("✅ Vertex AI initialized!")

# Example 1: List existing resources
print("\n" + "="*70)
print("Example 1: List Existing Resources")
print("="*70)

try:
    models = aiplatform.Model.list()
    model_list = list(models)
    print(f"📊 Models: {len(model_list)}")
    for model in model_list[:5]:  # Show first 5
        print(f"   - {model.display_name} (ID: {model.resource_name})")
    
    endpoints = aiplatform.Endpoint.list()
    endpoint_list = list(endpoints)
    print(f"🔗 Endpoints: {len(endpoint_list)}")
    for endpoint in endpoint_list[:5]:
        print(f"   - {endpoint.display_name} (ID: {endpoint.resource_name})")
        
except Exception as e:
    print(f"⚠️  Error listing resources: {e}")

# Example 2: Use Vertex AI Prediction API (pre-trained models)
print("\n" + "="*70)
print("Example 2: Using Vertex AI Prediction API")
print("="*70)
print("💡 You can use Vertex AI's pre-trained models via REST API")
print("   Examples: Text-to-Text, Image Classification, etc.")
print("   See: https://cloud.google.com/vertex-ai/docs/predictions/get-predictions")

# Example 3: Create a simple dataset (if you have data)
print("\n" + "="*70)
print("Example 3: Working with Datasets")
print("="*70)
print("💡 You can create datasets from your GCS data:")
print("""
from google.cloud import aiplatform
from google.cloud.aiplatform import datasets

# Create a tabular dataset from GCS
dataset = datasets.TabularDataset.create(
    display_name="my-dataset",
    gcs_source=["gs://your-bucket/your-data.csv"],
    project=project_id,
    location=region
)
print(f"Created dataset: {dataset.resource_name}")
""")

# Example 4: Use Model Garden (pre-trained models)
print("\n" + "="*70)
print("Example 4: Using Model Garden")
print("="*70)
print("💡 Vertex AI Model Garden has pre-trained models you can use:")
print("   - Text models (BERT, GPT, etc.)")
print("   - Vision models")
print("   - AutoML models")
print("   See: https://console.cloud.google.com/vertex-ai/model-garden")

# Example 5: Batch Prediction
print("\n" + "="*70)
print("Example 5: Batch Predictions")
print("="*70)
print("💡 You can run batch predictions on data in GCS:")
print("""
from google.cloud.aiplatform import jobs

# Create a batch prediction job
batch_prediction_job = jobs.BatchPredictionJob.create(
    job_display_name="my-batch-prediction",
    model_name="your-model-resource-name",
    instances_format="csv",
    predictions_format="csv",
    gcs_source="gs://your-bucket/input-data.csv",
    gcs_destination_prefix="gs://your-bucket/predictions/",
    project=project_id,
    location=region
)
""")

# Example 6: Use Vertex AI for ML workflows
print("\n" + "="*70)
print("Example 6: ML Workflows")
print("="*70)
print("💡 You can:")
print("   1. Train custom models")
print("   2. Deploy models to endpoints")
print("   3. Run online predictions")
print("   4. Monitor model performance")
print("   See: https://cloud.google.com/vertex-ai/docs")

print("\n" + "="*70)
print("✅ Vertex AI is ready to use!")
print("="*70)
print("\n💡 Next Steps:")
print("   1. Explore Model Garden for pre-trained models")
print("   2. Create datasets from your GCS data")
print("   3. Train or deploy models")
print("   4. Run predictions on your data")
print("\n📚 Documentation: https://cloud.google.com/vertex-ai/docs")
print("="*70)

