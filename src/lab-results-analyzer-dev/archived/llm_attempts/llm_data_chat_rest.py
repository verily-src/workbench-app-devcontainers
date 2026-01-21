#!/usr/bin/env python3
"""
LLM Data Chat using REST API (Alternative when SDK models aren't available)
Uses Vertex AI REST API directly which sometimes works when SDK doesn't.
"""

import sys
import subprocess
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
import requests
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import storage

print("="*70)
print("🤖 LLM Data Chat (REST API Version)")
print("="*70)

# Install packages
try:
    from google.auth.transport.requests import Request
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", 
                          "google-auth", "google-cloud-storage", "requests"])

# Configuration
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"
region = "us-central1"

# Get credentials
creds, project_id = default()
creds.refresh(Request())

print(f"✅ Authenticated (Project: {project_id})")

# Load data
print(f"\n📥 Loading data from GCS...")
client = storage.Client()
bucket = client.bucket(GCS_BUCKET)
blob = bucket.blob(FILE_NAME)
temp_file = "/tmp/data.csv"
blob.download_to_filename(temp_file)
df = pd.read_csv(temp_file)
os.remove(temp_file)

print(f"✅ Data loaded: {len(df)} rows × {len(df.columns)} columns")
print(f"📋 Columns: {list(df.columns)}")

# Create data summary
data_summary = f"""
Dataset: {len(df)} rows, {len(df.columns)} columns
Columns: {', '.join(df.columns)}
Sample data:
{df.head().to_string()}
"""

def ask_question_rest(question):
    """Ask question using REST API."""
    
    # Try different endpoints
    endpoints = [
        f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/publishers/google/models/gemini-pro:generateContent",
        f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/publishers/google/models/gemini-1.5-pro:generateContent",
        f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project_id}/locations/us-central1/publishers/google/models/gemini-pro:generateContent",
    ]
    
    prompt = f"""You are a data analyst. Analyze this data:

{data_summary}

User question: "{question}"

Generate Python pandas code to answer this. Use 'df' for DataFrame.
If visualization needed, save to 'output.png'.
Return ONLY executable Python code, no markdown."""

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
            print(f"🔍 Trying endpoint: {endpoint.split('/')[-2]}")
            response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and len(result['candidates']) > 0:
                    content = result['candidates'][0]['content']['parts'][0]['text']
                    print("✅ Got response from API")
                    return content
            elif response.status_code == 404:
                print(f"   ⚠️  404 - Model not found")
                continue
            else:
                print(f"   ⚠️  Status {response.status_code}: {response.text[:100]}")
                continue
        except Exception as e:
            print(f"   ⚠️  Error: {str(e)[:100]}")
            continue
    
    return None

# Interactive chat
print("\n" + "="*70)
print("💬 Interactive Data Chat (REST API)")
print("="*70)
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
        
        code = ask_question_rest(question)
        
        if not code:
            print("❌ Could not get response from API")
            print("\n💡 This might mean:")
            print("   1. Generative AI API is not enabled")
            print("   2. You don't have access to Gemini models")
            print("   3. Try the fallback version: llm_data_chat_fallback.py")
            continue
        
        # Clean code
        if '```python' in code:
            code = code.split('```python')[1].split('```')[0].strip()
        elif '```' in code:
            code = code.split('```')[1].split('```')[0].strip()
        
        print(f"\n📝 Generated code:\n{code}\n")
        
        # Execute
        try:
            exec(code, {'df': df, 'pd': pd, 'np': np, 'plt': plt, 'sns': sns})
            print("✅ Executed successfully!")
            if os.path.exists('output.png'):
                print("📊 Visualization: output.png")
        except Exception as e:
            print(f"⚠️  Execution error: {e}")
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        break
    except Exception as e:
        print(f"❌ Error: {e}")

