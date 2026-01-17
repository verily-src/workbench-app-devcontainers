#!/usr/bin/env python3
"""
LLM-Powered Data Chat Interface
Ask questions in natural language about your GCS data and get answers with visualizations.
Uses Vertex AI Gemini to understand questions and analyze your data.
"""

import sys
import subprocess
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
from io import StringIO
import traceback

print("="*70)
print("🤖 LLM-Powered Data Chat Interface")
print("="*70)

# Install required packages
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from google.auth import default
    from google.cloud import storage
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", 
                          "google-cloud-aiplatform", "google-cloud-storage", 
                          "pandas", "matplotlib", "seaborn"])
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from google.auth import default
    from google.cloud import storage

# Configuration
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"
FILE_FORMAT = "csv"

# Initialize Vertex AI
credentials, project_id = default()
region = "us-central1"

vertexai.init(project=project_id, location=region)
model = GenerativeModel("gemini-1.5-pro")

print(f"✅ Vertex AI initialized (Project: {project_id}, Region: {region})")
print(f"✅ Using Gemini 1.5 Pro model")

# Load data from GCS
print(f"\n📥 Loading data from GCS...")
def load_data_from_gcs(bucket_name, file_name, file_format="csv"):
    """Load data from GCS bucket."""
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        
        temp_file = f"/tmp/{os.path.basename(file_name)}"
        blob.download_to_filename(temp_file)
        
        if file_format.lower() == "csv":
            df = pd.read_csv(temp_file)
        elif file_format.lower() == "parquet":
            df = pd.read_parquet(temp_file)
        elif file_format.lower() == "json":
            df = pd.read_json(temp_file)
        else:
            df = pd.read_csv(temp_file)
        
        os.remove(temp_file)
        return df
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        raise

df = load_data_from_gcs(GCS_BUCKET, FILE_NAME, FILE_FORMAT)
print(f"✅ Data loaded: {len(df)} rows × {len(df.columns)} columns")
print(f"📋 Columns: {list(df.columns)}")

# Create data summary for the LLM
data_summary = f"""
Dataset Information:
- Rows: {len(df)}
- Columns: {len(df.columns)}
- Column names: {', '.join(df.columns)}
- Data types: {dict(df.dtypes)}
- Sample data (first 5 rows):
{df.head().to_string()}
- Basic statistics:
{df.describe().to_string() if len(df.select_dtypes(include=[np.number]).columns) > 0 else 'No numeric columns'}
"""

# Function to generate and execute code
def ask_question(question, show_code=False):
    """Ask a question about the data and get an answer."""
    
    prompt = f"""You are a data analyst assistant. You have access to a pandas DataFrame called 'df' with the following information:

{data_summary}

The user asks: "{question}"

Your task:
1. Understand what the user wants to know
2. Generate Python/pandas code to answer the question
3. If visualization is needed, create it using matplotlib/seaborn
4. Provide a natural language summary of the findings

IMPORTANT:
- Only generate executable Python code
- Use the DataFrame 'df' that is already loaded
- Save visualizations to files if created (e.g., 'output.png')
- Return your response in this JSON format:
{{
    "code": "python code here",
    "explanation": "natural language explanation of what the code does",
    "visualization": true/false,
    "summary": "summary of findings after code execution"
}}

Generate the code and response now:"""

    try:
        response = model.generate_content(prompt)
        response_text = response.text
        
        # Try to extract JSON from response
        try:
            # Find JSON in the response
            if '{' in response_text and '}' in response_text:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)
            else:
                # If no JSON, try to extract code from markdown code blocks
                if '```python' in response_text:
                    code_start = response_text.find('```python') + 9
                    code_end = response_text.find('```', code_start)
                    code = response_text[code_start:code_end].strip()
                    result = {
                        "code": code,
                        "explanation": response_text,
                        "visualization": False,
                        "summary": ""
                    }
                else:
                    # Fallback: treat entire response as code
                    result = {
                        "code": response_text,
                        "explanation": "Generated code",
                        "visualization": False,
                        "summary": ""
                    }
        except json.JSONDecodeError:
            # If JSON parsing fails, extract code from markdown
            if '```python' in response_text:
                code_start = response_text.find('```python') + 9
                code_end = response_text.find('```', code_start)
                code = response_text[code_start:code_end].strip()
            elif '```' in response_text:
                code_start = response_text.find('```') + 3
                code_end = response_text.find('```', code_start)
                code = response_text[code_start:code_end].strip()
            else:
                code = response_text.strip()
            
            result = {
                "code": code,
                "explanation": response_text,
                "visualization": False,
                "summary": ""
            }
        
        if show_code:
            print(f"\n📝 Generated Code:\n{result['code']}\n")
        
        # Execute the code
        print(f"\n🔍 Executing analysis...")
        try:
            # Create a safe execution environment
            exec_globals = {
                'df': df,
                'pd': pd,
                'np': np,
            }
            exec_locals = {}
            
            exec(result['code'], exec_globals, exec_locals)
            
            print("✅ Code executed successfully!")
            
            # Check if visualization was created
            if os.path.exists('output.png'):
                print("📊 Visualization saved as 'output.png'")
                result['visualization'] = True
                result['visualization_file'] = 'output.png'
            
        except Exception as e:
            print(f"⚠️  Error executing code: {e}")
            print(f"   Traceback: {traceback.format_exc()}")
            result['execution_error'] = str(e)
        
        return result
        
    except Exception as e:
        print(f"❌ Error generating response: {e}")
        return {"error": str(e)}

# Interactive chat loop
print("\n" + "="*70)
print("💬 Interactive Data Chat")
print("="*70)
print("Ask questions about your data in natural language!")
print("Examples:")
print("  - 'What are the top 10 values in the first column?'")
print("  - 'Show me a histogram of numeric columns'")
print("  - 'What is the summary statistics of this dataset?'")
print("  - 'Create a correlation heatmap'")
print("  - 'What columns have missing values?'")
print("\nType 'quit' or 'exit' to stop")
print("="*70)

while True:
    try:
        question = input("\n❓ Your question: ").strip()
        
        if question.lower() in ['quit', 'exit', 'q']:
            print("\n👋 Goodbye!")
            break
        
        if not question:
            continue
        
        print(f"\n🤔 Processing: {question}")
        result = ask_question(question, show_code=True)
        
        if 'error' in result:
            print(f"❌ Error: {result['error']}")
        else:
            if 'explanation' in result and result['explanation']:
                print(f"\n💡 Explanation:\n{result['explanation']}")
            
            if result.get('visualization') and 'visualization_file' in result:
                print(f"\n📊 Visualization created: {result['visualization_file']}")
            
            if 'summary' in result and result['summary']:
                print(f"\n📝 Summary:\n{result['summary']}")
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        break
    except Exception as e:
        print(f"\n❌ Error: {e}")

