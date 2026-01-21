#!/usr/bin/env python3
"""
Fallback Data Chat - Works without Gemini/LLM access
Uses rule-based natural language processing to answer questions about data.
"""

import sys
import subprocess
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import re
from google.cloud import storage

print("="*70)
print("🤖 Data Chat (Fallback - No LLM Required)")
print("="*70)

# Configuration
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"

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

def interpret_question(question):
    """Interpret natural language question and generate code."""
    question_lower = question.lower()
    
    # Pattern matching for common questions
    if any(word in question_lower for word in ['summary', 'statistics', 'describe', 'overview']):
        return {
            'code': 'print(df.describe())\nprint(f"\\nData types:\\n{df.dtypes}")\nprint(f"\\nMissing values:\\n{df.isnull().sum()}")',
            'explanation': 'Showing summary statistics, data types, and missing values'
        }
    
    elif any(word in question_lower for word in ['histogram', 'distribution', 'dist']):
        # Find numeric columns
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            col = numeric_cols[0]
            return {
                'code': f'plt.figure(figsize=(10, 6))\ndf["{col}"].hist(bins=30)\nplt.title("Distribution of {col}")\nplt.xlabel("{col}")\nplt.ylabel("Frequency")\nplt.savefig("output.png")\nplt.show()',
                'explanation': f'Creating histogram of {col}'
            }
        else:
            return {'code': 'print("No numeric columns found for histogram")', 'explanation': 'No numeric columns'}
    
    elif any(word in question_lower for word in ['correlation', 'correlate', 'heatmap']):
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) > 1:
            return {
                'code': 'plt.figure(figsize=(10, 8))\nsns.heatmap(df.select_dtypes(include=[np.number]).corr(), annot=True, cmap="coolwarm")\nplt.title("Correlation Heatmap")\nplt.tight_layout()\nplt.savefig("output.png")\nplt.show()',
                'explanation': 'Creating correlation heatmap'
            }
        else:
            return {'code': 'print("Need at least 2 numeric columns for correlation")', 'explanation': 'Not enough numeric columns'}
    
    elif any(word in question_lower for word in ['top', 'highest', 'maximum', 'max']):
        # Try to find column name
        for col in df.columns:
            if col.lower() in question_lower:
                return {
                    'code': f'print(f"Top 10 values in {col}:")\nprint(df["{col}"].value_counts().head(10))',
                    'explanation': f'Showing top values in {col}'
                }
        # Default to first column
        col = df.columns[0]
        return {
            'code': f'print(f"Top 10 values in {col}:")\nprint(df["{col}"].value_counts().head(10))',
            'explanation': f'Showing top values in {col}'
        }
    
    elif any(word in question_lower for word in ['missing', 'null', 'na', 'empty']):
        return {
            'code': 'missing = df.isnull().sum()\nprint("Missing values per column:")\nprint(missing[missing > 0] if missing.sum() > 0 else "No missing values")',
            'explanation': 'Checking for missing values'
        }
    
    elif any(word in question_lower for word in ['unique', 'distinct', 'different']):
        # Find column
        for col in df.columns:
            if col.lower() in question_lower:
                return {
                    'code': f'print(f"Unique values in {col}: {df[\\"{col}\\"].nunique()}")\nprint(f"\\nValue counts:\\n{df[\\"{col}\\"].value_counts()}")',
                    'explanation': f'Showing unique values in {col}'
                }
        return {
            'code': 'for col in df.columns:\n    print(f"{col}: {df[col].nunique()} unique values")',
            'explanation': 'Showing unique value counts for all columns'
        }
    
    elif any(word in question_lower for word in ['plot', 'chart', 'graph', 'visualize']):
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            col = numeric_cols[0]
            return {
                'code': f'plt.figure(figsize=(10, 6))\ndf["{col}"].plot(kind="line")\nplt.title("{col} over index")\nplt.ylabel("{col}")\nplt.savefig("output.png")\nplt.show()',
                'explanation': f'Plotting {col}'
            }
        else:
            return {'code': 'print("No numeric columns to plot")', 'explanation': 'No numeric columns'}
    
    elif any(word in question_lower for word in ['head', 'first', 'sample']):
        num = 10
        if '5' in question or 'five' in question_lower:
            num = 5
        return {
            'code': f'print(f"First {num} rows:")\nprint(df.head({num}))',
            'explanation': f'Showing first {num} rows'
        }
    
    elif any(word in question_lower for word in ['info', 'columns', 'structure']):
        return {
            'code': 'print(f"Dataset shape: {df.shape}")\nprint(f"\\nColumns: {list(df.columns)}")\nprint(f"\\nData types:\\n{df.dtypes}")\nprint(f"\\nMemory usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")',
            'explanation': 'Showing dataset information'
        }
    
    else:
        # Default: show basic info
        return {
            'code': 'print("I can help with:")\nprint("- Summary statistics")\nprint("- Visualizations (histogram, correlation)")\nprint("- Top values")\nprint("- Missing values")\nprint("- Unique values")\nprint("\\nTry asking: \\"show summary statistics\\" or \\"create a histogram\\"")',
            'explanation': 'Showing help'
        }

# Interactive chat
print("\n" + "="*70)
print("💬 Data Chat (Rule-based)")
print("="*70)
print("I can answer questions about:")
print("  - Summary statistics")
print("  - Visualizations (histograms, heatmaps, plots)")
print("  - Top/maximum values")
print("  - Missing values")
print("  - Unique values")
print("  - Data structure")
print("\nType 'quit' to exit")
print("="*70)

while True:
    try:
        question = input("\n❓ Your question: ").strip()
        
        if question.lower() in ['quit', 'exit', 'q']:
            break
        
        if not question:
            continue
        
        print(f"\n🤔 Processing: {question}")
        result = interpret_question(question)
        
        print(f"\n💡 {result['explanation']}")
        print(f"\n📝 Executing code...")
        
        try:
            exec(result['code'], {'df': df, 'pd': pd, 'np': np, 'plt': plt, 'sns': sns})
            print("✅ Done!")
            if os.path.exists('output.png'):
                print("📊 Visualization saved as output.png")
        except Exception as e:
            print(f"⚠️  Error: {e}")
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        break
    except Exception as e:
        print(f"❌ Error: {e}")

