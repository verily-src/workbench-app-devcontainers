#!/usr/bin/env python3
"""
Data Profiling Analysis - Auto-run Script
This script automatically loads data from GCS and generates a profiling report.
Double-click this file to run it, or run: python run_data_profiling.py
"""

import pandas as pd
import numpy as np
import os
import sys
import subprocess
from pathlib import Path

# ============================================================================
# CONFIGURATION: Data Collection Bucket and File
# ============================================================================
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"  # Your data collection bucket
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"   # Your data file
FILE_FORMAT = "csv"  # File format

# ============================================================================
# CONFIGURATION: OpenAI API Key from Secret Manager
# ============================================================================
# OpenAI secret configuration
PROJECT_ID = "wb-smart-cabbage-5940"  # Your GCP project ID
TEAM_ALIAS = "php-product-"  # Your team alias (with trailing dash)
SECRET_VERSION = "live"  # Use "latest" or "live" depending on your setup
USE_OPENAI = True  # Set to False to skip OpenAI integration

# Secret name is constructed as: {team_alias}openai-api-key
# Full path: projects/{PROJECT_ID}/secrets/{TEAM_ALIAS}openai-api-key/versions/{SECRET_VERSION}

print("="*70)
print("📊 Data Profiling Analysis - Auto-run")
print("="*70)
print(f"Bucket: {GCS_BUCKET}")
print(f"File: {FILE_NAME}")
print(f"Format: {FILE_FORMAT}")
print(f"GCS Path: gs://{GCS_BUCKET}/{FILE_NAME}")
print("="*70)

# Install google-cloud-storage if needed
try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("ℹ️  Installing google-cloud-storage...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-storage"])
    from google.cloud import storage
    GCS_AVAILABLE = True
    print("✅ google-cloud-storage installed successfully!")

# Install ydata-profiling if needed
try:
    from ydata_profiling import ProfileReport
    print("✅ ydata-profiling is available")
except ImportError:
    print("ℹ️  Installing ydata-profiling...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "ydata-profiling"])
    from ydata_profiling import ProfileReport
    print("✅ ydata-profiling installed successfully!")

# Install OpenAI and Secret Manager packages if needed
openai_client = None
if USE_OPENAI:
    try:
        from google.cloud import secretmanager
        import openai
        print("✅ google-cloud-secret-manager and openai are available")
    except ImportError:
        print("ℹ️  Installing google-cloud-secret-manager and openai...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-secret-manager", "openai"])
        from google.cloud import secretmanager
        import openai
        print("✅ Packages installed successfully!")

# Fix: Patch numpy.asarray to handle copy parameter compatibility
import numpy as np
original_asarray = np.asarray

def patched_asarray(a, dtype=None, order=None, copy=None, **kwargs):
    """Patched asarray that handles copy parameter for older numpy versions."""
    try:
        if copy is not None:
            return original_asarray(a, dtype=dtype, order=order, copy=copy, **kwargs)
        else:
            return original_asarray(a, dtype=dtype, order=order, **kwargs)
    except TypeError:
        if 'copy' in kwargs:
            kwargs.pop('copy')
        return original_asarray(a, dtype=dtype, order=order, **kwargs)

np.asarray = patched_asarray
print("✅ Patched numpy.asarray for compatibility")

# Also disable word cloud generation as backup
try:
    import ydata_profiling.visualisation.plot as plot_module
    
    def noop_plot_word_cloud(config, word_counts):
        """Disabled word cloud to avoid issues."""
        return ""
    
    plot_module.plot_word_cloud = noop_plot_word_cloud
    if hasattr(plot_module, '_plot_word_cloud'):
        plot_module._plot_word_cloud = lambda config, series, figsize=None: None
    
    print("✅ Word cloud generation disabled")
except Exception as e:
    print(f"ℹ️  Could not disable word cloud: {e}")

# ============================================================================
# OpenAI Integration Functions
# ============================================================================

def get_openai_key_from_secret(project_id, team_alias, secret_version="live"):
    """Retrieve OpenAI API key from Google Cloud Secret Manager.
    
    Args:
        project_id: GCP project ID
        team_alias: Team alias (e.g., "php-product-") - should end with dash
        secret_version: Secret version ("live" or "latest")
    
    Returns:
        API key as string
    """
    try:
        # Construct secret name: {team_alias}openai-api-key
        secret_name = f"{team_alias}openai-api-key"
        secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        
        print(f"\n🔐 Retrieving OpenAI API key from Secret Manager...")
        print(f"   Project: {project_id}")
        print(f"   Team Alias: {team_alias}")
        print(f"   Secret Name: {secret_name}")
        print(f"   Secret Path: {secret_path}")
        
        secret_client = secretmanager.SecretManagerServiceClient()
        response = secret_client.access_secret_version(name=secret_path)
        api_key = response.payload.data.decode("UTF-8")
        
        print("✅ OpenAI API key retrieved successfully!")
        return api_key
    except Exception as e:
        print(f"❌ Error retrieving OpenAI API key: {e}")
        print("💡 Make sure:")
        print("   - Service account has access to the secret")
        print("   - Secret path is correct")
        print("   - Team alias is correct (should end with dash, e.g., 'php-product-')")
        print("   - You're in the correct GCP project")
        raise

def initialize_openai_client(api_key):
    """Initialize OpenAI client with API key."""
    try:
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://us.api.openai.com/v1/",
        )
        print("✅ OpenAI client initialized successfully!")
        return client
    except Exception as e:
        print(f"❌ Error initializing OpenAI client: {e}")
        raise

def get_data_summary_with_openai(client, df, sample_rows=5):
    """Use OpenAI to generate a natural language summary of the data."""
    try:
        # Create a summary of the data
        data_summary = f"""
        Dataset Overview:
        - Rows: {len(df)}
        - Columns: {len(df.columns)}
        - Column names: {', '.join(df.columns.tolist())}
        - Data types: {df.dtypes.to_dict()}
        - Missing values: {df.isnull().sum().to_dict()}
        
        Sample data (first {sample_rows} rows):
        {df.head(sample_rows).to_string()}
        """
        
        print("\n🤖 Generating AI-powered data summary...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a data analyst. Provide concise, insightful summaries of datasets."
                },
                {
                    "role": "user",
                    "content": f"Analyze this dataset and provide a brief summary highlighting key characteristics, data quality issues, and interesting patterns:\n\n{data_summary}"
                }
            ],
            max_tokens=500,
            temperature=0.7
        )
        
        ai_summary = response.choices[0].message.content
        print("✅ AI summary generated!")
        return ai_summary
    except Exception as e:
        print(f"⚠️  Error generating AI summary: {e}")
        return None

# Initialize OpenAI if enabled
if USE_OPENAI:
    try:
        openai_key = get_openai_key_from_secret(PROJECT_ID, TEAM_ALIAS, SECRET_VERSION)
        openai_client = initialize_openai_client(openai_key)
    except Exception as e:
        print(f"⚠️  OpenAI integration disabled due to error: {e}")
        print("   Continuing with data profiling only...")
        USE_OPENAI = False
        openai_client = None

# ============================================================================
# Load Data from GCS Bucket
# ============================================================================

def load_data_from_gcs(bucket_name, file_name, file_format="csv"):
    """Load data from GCS bucket using Google Cloud Storage client."""
    try:
        # Initialize GCS client
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        
        print(f"\n📥 Reading file from GCS: gs://{bucket_name}/{file_name}")
        
        # Download to temporary file
        temp_file = f"/tmp/{os.path.basename(file_name)}"
        blob.download_to_filename(temp_file)
        print(f"✅ File downloaded to: {temp_file}")
        
        # Read based on file format
        if file_format.lower() == "csv":
            df = pd.read_csv(temp_file)
        elif file_format.lower() == "parquet":
            df = pd.read_parquet(temp_file)
        elif file_format.lower() == "json":
            df = pd.read_json(temp_file)
        elif file_format.lower() == "excel":
            df = pd.read_excel(temp_file)
        else:
            raise ValueError(f"Unsupported file format: {file_format}")
        
        # Clean up temp file
        os.remove(temp_file)
        print(f"✅ Data loaded successfully: {len(df)} rows, {len(df.columns)} columns")
        return df
        
    except Exception as e:
        print(f"❌ Error loading from GCS: {e}")
        raise

# Load data from GCS
print("\n" + "="*70)
print("Loading data from data collection...")
print("="*70)
bucket_name = GCS_BUCKET.replace("gs://", "").strip()
df = load_data_from_gcs(bucket_name, FILE_NAME, FILE_FORMAT)

print(f"\n✅ Dataset ready: {len(df)} records")
print(f"📋 Columns: {list(df.columns)}")
print(f"\n📊 First few records:")
print(df.head(10))

# ============================================================================
# Generate Profiling Report
# ============================================================================

print("\n" + "="*70)
print("📊 Generating Comprehensive Data Profiling Report...")
print("="*70)
print("This may take a few moments depending on your data size...")

# Create profile report
profile = ProfileReport(
    df,
    title="Data Profiling Report",
    explorative=True,  # Comprehensive analysis
    minimal=False,  # Set to True for very large datasets
    progress_bar=True
)

# Save report to HTML file
report_file = "data_profile_report.html"
report_path = os.path.abspath(report_file)

print(f"\n💾 Saving report to: {report_path}")
profile.to_file(report_file)
print(f"✅ Report saved successfully!")
print(f"📁 Full path: {report_path}")

# Open the report in the default browser
try:
    import webbrowser
    file_url = f"file://{report_path}"
    print(f"\n🌐 Opening report in browser...")
    webbrowser.open(file_url)
    print("✅ Report opened in browser!")
except Exception as e:
    print(f"ℹ️  Could not open browser automatically: {e}")
    print(f"   Please open the file manually: {report_path}")

# ============================================================================
# Optional: Generate AI-Powered Summary
# ============================================================================

if USE_OPENAI and openai_client is not None:
    try:
        print("\n" + "="*70)
        print("🤖 Generating AI-Powered Data Summary...")
        print("="*70)
        
        ai_summary = get_data_summary_with_openai(openai_client, df)
        
        if ai_summary:
            print("\n" + "="*70)
            print("📝 AI-Generated Summary:")
            print("="*70)
            print(ai_summary)
            print("="*70)
            
            # Save AI summary to file
            summary_file = "ai_data_summary.txt"
            with open(summary_file, "w") as f:
                f.write("AI-Powered Data Summary\n")
                f.write("="*70 + "\n\n")
                f.write(ai_summary)
            print(f"\n💾 AI summary saved to: {summary_file}")
    except Exception as e:
        print(f"⚠️  Could not generate AI summary: {e}")
        print("   This is optional - data profiling report is still complete.")

print("\n" + "="*70)
print("✅ Profiling Report Complete!")
print(f"📄 Report saved as: {report_file}")
if USE_OPENAI and openai_client is not None:
    print("🤖 OpenAI integration: Active")
else:
    print("🤖 OpenAI integration: Disabled")
print("="*70)

