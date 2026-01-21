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
- File: gs://{GCS_BUCKET}/{FILE_NAME}
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

def generate_fallback_code(question):
    """Fallback rule-based code generation if LLM fails."""
    q_lower = question.lower()
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
    all_cols = list(df.columns)
    
    def find_column(q, cols):
        for col in cols:
            if col.lower() in q.lower():
                return col
        return None
    
    # Data completeness
    if any(w in q_lower for w in ['completeness', 'complete', 'missing', 'null', 'na', 'empty', 'data quality']):
        return '''
missing = df.isnull().sum()
completeness = ((len(df) - missing) / len(df) * 100).round(2)
completeness_df = pd.DataFrame({
    'Column': df.columns,
    'Missing Count': missing.values,
    'Completeness %': completeness.values
}).sort_values('Completeness %')
print("="*70)
print("📊 Data Completeness Report")
print("="*70)
print(completeness_df.to_string(index=False))
print(f"\\nOverall: {completeness.mean():.2f}% average completeness")
print("="*70)
''', 'Data completeness analysis'
    
    # Summary/Statistics
    elif any(w in q_lower for w in ['summary', 'statistics', 'describe', 'overview', 'characterize']):
        return '''
print("="*70)
print("📊 Dataset Summary")
print("="*70)
print(f"Shape: {len(df):,} rows × {len(df.columns)} columns")
print(f"\\nColumns: {list(df.columns)}")
if len(numeric_cols) > 0:
    print(f"\\nNumeric Summary:\\n{df[numeric_cols].describe()}")
missing = df.isnull().sum()
if missing.sum() > 0:
    print(f"\\nMissing Values:\\n{missing[missing > 0]}")
else:
    print("\\n✅ No missing values")
print("="*70)
''', 'Dataset summary'
    
    # Histogram
    elif any(w in q_lower for w in ['histogram', 'distribution', 'dist', 'hist']):
        col = find_column(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            return f'''
plt.figure(figsize=(12, 6))
df["{col}"].hist(bins=30, edgecolor='black', alpha=0.7)
plt.title(f"Distribution of {col}", fontsize=14, fontweight='bold')
plt.xlabel("{col}", fontsize=12)
plt.ylabel("Frequency", fontsize=12)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print(f"✅ Histogram saved as output.png")
''', f'Histogram of {col}'
        return 'print("❌ No numeric columns")', 'No numeric columns'
    
    # Correlation
    elif any(w in q_lower for w in ['correlation', 'correlate', 'heatmap']):
        if len(numeric_cols) > 1:
            return '''
plt.figure(figsize=(12, 10))
corr = df[numeric_cols].corr()
sns.heatmap(corr, annot=True, fmt='.2f', cmap='coolwarm', center=0, square=True)
plt.title("Correlation Heatmap", fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print("✅ Correlation heatmap saved as output.png")
''', 'Correlation heatmap'
        return 'print("❌ Need 2+ numeric columns")', 'Not enough columns'
    
    # Top values
    elif any(w in q_lower for w in ['top', 'highest', 'maximum', 'max']):
        col = find_column(question, all_cols) or all_cols[0]
        num = 10
        import re
        if re.search(r'\d+', question):
            num = int(re.search(r'\d+', question).group())
        return f'''
print(f"Top {num} values in '{col}':")
if "{col}" in {numeric_cols}:
    print(df.nlargest({num}, "{col}")[["{col}"]].to_string())
else:
    print(df["{col}"].value_counts().head({num}).to_string())
''', f'Top {num} values in {col}'
    
    # Default
    return '''
print("I can help with: completeness, summary, histogram, correlation, top values")
print("Try: 'show data completeness' or 'create histogram'")
''', 'Help'

def ask_llm(question):
    """Ask LLM to generate code, with fallback to rule-based."""
    code = None
    explanation = None
    
    # Try LLM first
    if USE_OPENAI:
        print("🤖 Using OpenAI GPT-4...")
        code = call_openai(question)
    elif USE_GEMINI:
        print("🤖 Using Gemini via REST API...")
        code = call_gemini_rest(question)
    
    # If LLM fails, use fallback
    if not code:
        print("⚠️  LLM not available, using intelligent fallback...")
        code, explanation = generate_fallback_code(question)
        print(f"💡 {explanation}")
    
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
            # Get column info for fallback functions
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
            
            exec(code, {
                'df': df,
                'pd': pd,
                'np': np,
                'plt': plt,
                'sns': sns,
                'numeric_cols': numeric_cols,
                'categorical_cols': categorical_cols
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

