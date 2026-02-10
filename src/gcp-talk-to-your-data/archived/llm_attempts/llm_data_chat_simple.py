#!/usr/bin/env python3
"""
Simplified LLM Data Chat - Single Question Mode
Ask one question and get an answer with visualization.
"""

import sys
import subprocess
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
from google.auth import default
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel

# Configuration
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"

# Initialize
print("Initializing...")
creds, project = default()
vertexai.init(project=project, location="us-central1")

# Try different model names
model = None
for model_name in ["gemini-pro", "gemini-1.5-pro", "gemini-1.0-pro", "text-bison@001"]:
    try:
        model = GenerativeModel(model_name)
        test_response = model.generate_content("test")
        print(f"✅ Using model: {model_name}")
        break
    except:
        continue

if model is None:
    print("❌ Could not initialize model. Please check API access.")
    sys.exit(1)

# Load data
print("Loading data...")
client = storage.Client()
bucket = client.bucket(GCS_BUCKET)
blob = bucket.blob(FILE_NAME)
temp_file = "/tmp/data.csv"
blob.download_to_filename(temp_file)
df = pd.read_csv(temp_file)
os.remove(temp_file)

print(f"✅ Data loaded: {len(df)} rows, {len(df.columns)} columns")

# Ask a question
if len(sys.argv) > 1:
    question = " ".join(sys.argv[1:])
else:
    question = input("Enter your question: ")

print(f"\n🤔 Question: {question}")

# Create prompt
prompt = f"""You are analyzing this dataset:
- Columns: {', '.join(df.columns)}
- Rows: {len(df)}
- Sample: {df.head().to_string()}

User question: "{question}"

Generate Python code to answer this. Use 'df' for the DataFrame.
If visualization needed, save to 'output.png'.
Return ONLY the Python code, no explanations."""

# Get response
response = model.generate_content(prompt)
code = response.text.strip()

# Clean code (remove markdown if present)
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
        print("📊 Visualization saved as output.png")
except Exception as e:
    print(f"❌ Error: {e}")

