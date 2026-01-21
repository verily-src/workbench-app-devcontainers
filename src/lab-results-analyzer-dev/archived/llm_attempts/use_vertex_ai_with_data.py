#!/usr/bin/env python3
"""
Example: Use Vertex AI with Your GCS Data
This shows how to connect your existing GCS data to Vertex AI.
"""

import sys
import subprocess

print("="*70)
print("🔗 Connecting Your GCS Data to Vertex AI")
print("="*70)

# Install packages
try:
    from google.cloud import aiplatform
    from google.cloud.aiplatform import datasets
    from google.auth import default
    from google.cloud import storage
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", 
                          "google-cloud-aiplatform", "google-cloud-storage"])
    from google.cloud import aiplatform
    from google.cloud.aiplatform import datasets
    from google.auth import default
    from google.cloud import storage

# Configuration
credentials, project_id = default()
region = "us-central1"

# Your existing GCS data
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"
GCS_PATH = f"gs://{GCS_BUCKET}/{FILE_NAME}"

print(f"\n📋 Project: {project_id}")
print(f"🌍 Region: {region}")
print(f"📊 Data: {GCS_PATH}")

# Initialize Vertex AI
aiplatform.init(project=project_id, location=region)
print("✅ Vertex AI initialized!")

# Example: Create a dataset from your GCS file
print("\n" + "="*70)
print("Example: Creating a Dataset from Your GCS Data")
print("="*70)

try:
    # Verify the file exists
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(FILE_NAME)
    
    if blob.exists():
        print(f"✅ Found data file: {GCS_PATH}")
        print(f"   File size: {blob.size / (1024*1024):.2f} MB")
        
        print("\n💡 To create a Vertex AI dataset, you can use:")
        print(f"""
from google.cloud.aiplatform import datasets

# Create a tabular dataset
dataset = datasets.TabularDataset.create(
    display_name="lab-results-dataset",
    gcs_source=["{GCS_PATH}"],
    project="{project_id}",
    location="{region}"
)

print(f"Created dataset: {{dataset.resource_name}}")
print(f"Dataset ID: {{dataset.name}}")
        """)
        
        print("⚠️  Note: Uncomment the code above to actually create the dataset")
        print("   (Commented out to avoid creating resources automatically)")
        
    else:
        print(f"❌ File not found: {GCS_PATH}")
        print("   Please check your bucket and file name")
        
except Exception as e:
    print(f"⚠️  Error accessing GCS: {e}")

# Example: What you can do with the dataset
print("\n" + "="*70)
print("What You Can Do Next:")
print("="*70)
print("""
1. Create a Dataset:
   - Use the dataset creation code above
   - This registers your GCS data with Vertex AI

2. Train a Model:
   - Use AutoML for tabular data
   - Or train a custom model

3. Run Predictions:
   - Deploy model to an endpoint
   - Make predictions on new data

4. Batch Processing:
   - Run batch predictions on large datasets
   - Process data in GCS directly
""")

print("\n" + "="*70)
print("✅ Ready to use Vertex AI with your data!")
print("="*70)

