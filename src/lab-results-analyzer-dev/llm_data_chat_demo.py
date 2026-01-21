#!/usr/bin/env python3
"""
LLM-Powered Data Chat - Uses LLM to generate code dynamically
Supports both OpenAI and Gemini (via REST API with Google auth)
"""

import sys
import os
import subprocess

# Auto-install required packages
def install_package(package):
    """Install package if not available."""
    try:
        __import__(package)
    except ImportError:
        print(f"Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

# Install dependencies
for pkg in ['pandas', 'numpy', 'matplotlib', 'seaborn', 'requests']:
    install_package(pkg)

# Now import
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import json
import re
from pathlib import Path
import requests

# Install google-cloud-storage if needed
try:
    from google.cloud import storage
except ImportError:
    print("Installing google-cloud-storage...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-storage"])
    from google.cloud import storage

print("="*70)
print("🤖 LLM-Powered Data Chat")
print("="*70)

# Try to get OpenAI API key from environment or user input
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
USE_OPENAI = False
USE_GEMINI = False

if OPENAI_API_KEY:
    USE_OPENAI = True
    print("✅ Found OpenAI API key in environment")
else:
    # Try to use Gemini with existing Google auth
    try:
        from google.auth import default
        from google.auth.transport.requests import Request
        creds, project_id = default()
        creds.refresh(Request())
        USE_GEMINI = True
        print(f"✅ Using Gemini via Google authentication (Project: {project_id})")
    except Exception as e:
        print(f"⚠️  Could not get Google credentials: {e}")
        api_key = input("\n🔑 Enter OpenAI API key (or press Enter to try Gemini REST): ").strip()
        if api_key:
            OPENAI_API_KEY = api_key
            USE_OPENAI = True
            print("✅ Using OpenAI")
        else:
            print("⚠️  No API key provided. Will try Gemini REST API...")
            USE_GEMINI = True

# Configuration - Same as notebook
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"
FILE_FORMAT = "csv"

# Load data from GCS - Same approach as notebook
print(f"\n📥 Loading data from GCS...")
def load_data_from_gcs(bucket_name, file_name, file_format="csv"):
    """Load data from GCS bucket - same function as notebook."""
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        
        print(f"📥 Reading file from GCS: gs://{bucket_name}/{file_name}")
        
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

# Load data from GCS (same as notebook)
bucket_name = GCS_BUCKET.replace("gs://", "").strip()
df = load_data_from_gcs(bucket_name, FILE_NAME, FILE_FORMAT)
print(f"📋 Columns: {', '.join(df.columns)}")

# Create data context for LLM
data_context = f"""
Dataset Information:
- File: {csv_file}
- Rows: {len(df)}
- Columns: {len(df.columns)}
- Column names: {', '.join(df.columns)}
- Data types: {dict(df.dtypes)}
- Numeric columns: {', '.join(df.select_dtypes(include=[np.number]).columns.tolist())}
- Categorical columns: {', '.join(df.select_dtypes(include=['object']).columns.tolist())}

Sample data (first 5 rows):
{df.head().to_string()}

Basic statistics:
{df.describe().to_string() if len(df.select_dtypes(include=[np.number]).columns) > 0 else 'No numeric columns'}
"""

def call_openai(question):
    """Call OpenAI API."""
    try:
        import openai
        if not hasattr(openai, 'OpenAI'):
            # Older API
            openai.api_key = OPENAI_API_KEY
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a data analyst. Generate Python pandas code to answer questions about data. Return ONLY executable Python code, no markdown."},
                    {"role": "user", "content": f"{data_context}\n\nUser question: {question}\n\nGenerate Python code using 'df' DataFrame. If visualization needed, save to 'output.png'."}
                ],
                temperature=0.3
            )
            return response.choices[0].message.content
        else:
            # New API
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a data analyst. Generate Python pandas code to answer questions about data. Return ONLY executable Python code, no markdown."},
                    {"role": "user", "content": f"{data_context}\n\nUser question: {question}\n\nGenerate Python code using 'df' DataFrame. If visualization needed, save to 'output.png'."}
                ],
                temperature=0.3
            )
            return response.choices[0].message.content
    except ImportError:
        print("Installing openai package...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "openai"])
        return call_openai(question)
    except Exception as e:
        print(f"❌ OpenAI error: {e}")
        return None

def call_gemini_rest(question):
    """Call Gemini via REST API using Google auth."""
    try:
        from google.auth import default
        from google.auth.transport.requests import Request
        creds, project_id = default()
        creds.refresh(Request())
        
        # Try different endpoints
        endpoints = [
            f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project_id}/locations/us-central1/publishers/google/models/gemini-pro:generateContent",
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
        ]
        
        prompt = f"""You are a data analyst. Generate Python pandas code to answer questions about data.

{data_context}

User question: {question}

Generate Python code using 'df' DataFrame. If visualization needed, save to 'output.png'.
Return ONLY executable Python code, no markdown, no explanations."""

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json"
        }
        
        for endpoint in endpoints:
            try:
                response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
                if response.status_code == 200:
                    result = response.json()
                    if 'candidates' in result and len(result['candidates']) > 0:
                        return result['candidates'][0]['content']['parts'][0]['text']
                elif response.status_code == 404:
                    continue
            except:
                continue
        
        return None
    except Exception as e:
        print(f"❌ Gemini REST error: {e}")
        return None

def ask_llm(question):
    """Ask LLM to generate code."""
    if USE_OPENAI:
        print("🤖 Using OpenAI GPT-4...")
        code = call_openai(question)
    elif USE_GEMINI:
        print("🤖 Using Gemini via REST API...")
        code = call_gemini_rest(question)
    else:
        return None
    
    if not code:
        return None
    
    # Clean code (remove markdown if present)
    if '```python' in code:
        code = code.split('```python')[1].split('```')[0].strip()
    elif '```' in code:
        code = code.split('```')[1].split('```')[0].strip()
    
    return code

# Interactive chat
print("\n" + "="*70)
print("💬 LLM-Powered Data Chat")
print("="*70)
print("Ask questions in natural language!")
print("The LLM will generate code to answer your questions.")
print("Type 'quit' to exit")
print("="*70)

while True:
    try:
        question = input("\n❓ Your question: ").strip()
        
        if question.lower() in ['quit', 'exit', 'q']:
            break
        
        if not question:
            continue
        
        print(f"\n🤔 Processing: {question}")
        code = ask_llm(question)
        
        if not code:
            print("❌ Could not get response from LLM")
            print("💡 Make sure you have:")
            if USE_OPENAI:
                print("   - Valid OpenAI API key")
            else:
                print("   - Google authentication working")
                print("   - Access to Gemini API")
            continue
        
        print(f"\n📝 Generated code:\n{code}\n")
        print("🔍 Executing...\n")
        
        try:
            exec(code, {
                'df': df,
                'pd': pd,
                'np': np,
                'plt': plt,
                'sns': sns
            })
            print("\n✅ Executed successfully!")
            if os.path.exists('output.png'):
                print("📊 Visualization saved as: output.png")
        except Exception as e:
            print(f"\n⚠️  Execution error: {e}")
            import traceback
            traceback.print_exc()
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        break
    except Exception as e:
        print(f"\n❌ Error: {e}")

