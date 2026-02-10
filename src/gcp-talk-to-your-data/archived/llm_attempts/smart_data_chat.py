#!/usr/bin/env python3
"""
Smart Data Chat - Advanced rule-based system (No Vertex AI required)
Uses intelligent pattern matching and code generation to answer data questions.
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
print("🤖 Smart Data Chat - No LLM Required")
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

# Get column info
numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
all_cols = list(df.columns)

def find_column_in_question(question, columns):
    """Find which column is mentioned in the question."""
    question_lower = question.lower()
    for col in columns:
        if col.lower() in question_lower:
            return col
    return None

def generate_code(question):
    """Generate Python code based on question patterns."""
    q_lower = question.lower()
    
    # Summary/Statistics
    if any(word in q_lower for word in ['summary', 'statistics', 'describe', 'overview', 'stats']):
        code = '''
print("="*70)
print("📊 Dataset Summary")
print("="*70)
print(f"Shape: {df.shape[0]} rows × {df.shape[1]} columns")
print(f"\\nColumn names: {list(df.columns)}")
print(f"\\nData types:\\n{df.dtypes}")
print(f"\\nMemory usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
if len(numeric_cols) > 0:
    print(f"\\nNumeric columns summary:\\n{df[numeric_cols].describe()}")
print(f"\\nMissing values:\\n{df.isnull().sum()[df.isnull().sum() > 0] if df.isnull().sum().sum() > 0 else 'No missing values'}")
'''
        return {'code': code, 'explanation': 'Showing comprehensive dataset summary'}
    
    # Histogram/Distribution
    elif any(word in q_lower for word in ['histogram', 'distribution', 'dist', 'hist']):
        col = find_column_in_question(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            code = f'''
plt.figure(figsize=(12, 6))
df["{col}"].hist(bins=30, edgecolor='black', alpha=0.7)
plt.title(f"Distribution of {col}", fontsize=14, fontweight='bold')
plt.xlabel("{col}", fontsize=12)
plt.ylabel("Frequency", fontsize=12)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print(f"✅ Histogram created for {col}")
'''
            return {'code': code, 'explanation': f'Creating histogram of {col}'}
        else:
            return {'code': 'print("❌ No numeric columns found for histogram")', 'explanation': 'No numeric columns'}
    
    # Correlation/Heatmap
    elif any(word in q_lower for word in ['correlation', 'correlate', 'heatmap', 'corr']):
        if len(numeric_cols) > 1:
            code = '''
plt.figure(figsize=(12, 10))
corr_matrix = df[numeric_cols].corr()
sns.heatmap(corr_matrix, annot=True, fmt='.2f', cmap='coolwarm', center=0, 
            square=True, linewidths=1, cbar_kws={"shrink": 0.8})
plt.title("Correlation Heatmap", fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print("✅ Correlation heatmap created")
'''
            return {'code': code, 'explanation': 'Creating correlation heatmap'}
        else:
            return {'code': 'print("❌ Need at least 2 numeric columns for correlation")', 'explanation': 'Not enough numeric columns'}
    
    # Top/Max values
    elif any(word in q_lower for word in ['top', 'highest', 'maximum', 'max', 'largest']):
        col = find_column_in_question(question, all_cols) or all_cols[0]
        num = 10
        if re.search(r'\d+', question):
            num = int(re.search(r'\d+', question).group())
        code = f'''
print(f"Top {num} values in '{col}':")
print("="*70)
if col in numeric_cols:
    top_values = df.nlargest({num}, col)[[col]]
    print(top_values.to_string())
    print(f"\\nMean: {{df[col].mean():.2f}}")
    print(f"Median: {{df[col].median():.2f}}")
else:
    top_counts = df[col].value_counts().head({num})
    print(top_counts.to_string())
    print(f"\\nTotal unique values: {{df[col].nunique()}}")
'''
        return {'code': code, 'explanation': f'Showing top {num} values in {col}'}
    
    # Missing values
    elif any(word in q_lower for word in ['missing', 'null', 'na', 'empty', 'nan']):
        code = '''
missing = df.isnull().sum()
missing_pct = (missing / len(df)) * 100
missing_df = pd.DataFrame({
    'Column': missing.index,
    'Missing Count': missing.values,
    'Missing %': missing_pct.values
})
missing_df = missing_df[missing_df['Missing Count'] > 0].sort_values('Missing Count', ascending=False)
if len(missing_df) > 0:
    print("Missing Values:")
    print("="*70)
    print(missing_df.to_string(index=False))
    print(f"\\nTotal missing values: {missing.sum()}")
else:
    print("✅ No missing values found!")
'''
        return {'code': code, 'explanation': 'Checking for missing values'}
    
    # Unique values
    elif any(word in q_lower for word in ['unique', 'distinct', 'different', 'unique values']):
        col = find_column_in_question(question, all_cols)
        if col:
            code = f'''
print(f"Unique values in '{col}':")
print("="*70)
print(f"Total unique: {{df['{col}'].nunique()}}")
print(f"Total rows: {{len(df)}}")
print(f"\\nValue counts:")
print(df['{col}'].value_counts().head(20).to_string())
'''
            return {'code': code, 'explanation': f'Showing unique values in {col}'}
        else:
            code = '''
print("Unique value counts per column:")
print("="*70)
for col in df.columns:
    print(f"{col}: {df[col].nunique()} unique values")
'''
            return {'code': code, 'explanation': 'Showing unique value counts for all columns'}
    
    # Plot/Chart/Visualize
    elif any(word in q_lower for word in ['plot', 'chart', 'graph', 'visualize', 'visualization']):
        col = find_column_in_question(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            code = f'''
plt.figure(figsize=(12, 6))
df["{col}"].plot(kind='line', linewidth=2)
plt.title(f"{col} over index", fontsize=14, fontweight='bold')
plt.xlabel("Index", fontsize=12)
plt.ylabel("{col}", fontsize=12)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print(f"✅ Plot created for {col}")
'''
            return {'code': code, 'explanation': f'Plotting {col}'}
        else:
            return {'code': 'print("❌ No numeric columns to plot")', 'explanation': 'No numeric columns'}
    
    # Box plot
    elif 'box' in q_lower and 'plot' in q_lower:
        col = find_column_in_question(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            code = f'''
plt.figure(figsize=(10, 6))
df["{col}"].plot(kind='box', vert=True)
plt.title(f"Box Plot of {col}", fontsize=14, fontweight='bold')
plt.ylabel("{col}", fontsize=12)
plt.grid(True, alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print(f"✅ Box plot created for {col}")
'''
            return {'code': code, 'explanation': f'Creating box plot of {col}'}
        else:
            return {'code': 'print("❌ No numeric columns for box plot")', 'explanation': 'No numeric columns'}
    
    # Count/Frequency
    elif any(word in q_lower for word in ['count', 'frequency', 'freq', 'how many']):
        col = find_column_in_question(question, all_cols) or all_cols[0]
        code = f'''
print(f"Value counts for '{col}':")
print("="*70)
counts = df['{col}'].value_counts()
print(counts.to_string())
print(f"\\nTotal: {{len(df)}} rows")
print(f"Unique values: {{df['{col}'].nunique()}}")
'''
        return {'code': code, 'explanation': f'Showing value counts for {col}'}
    
    # Mean/Average
    elif any(word in q_lower for word in ['mean', 'average', 'avg']):
        col = find_column_in_question(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            code = f'''
print(f"Statistics for '{col}':")
print("="*70)
print(f"Mean: {{df['{col}'].mean():.2f}}")
print(f"Median: {{df['{col}'].median():.2f}}")
print(f"Std Dev: {{df['{col}'].std():.2f}}")
print(f"Min: {{df['{col}'].min():.2f}}")
print(f"Max: {{df['{col}'].max():.2f}}")
'''
            return {'code': code, 'explanation': f'Showing statistics for {col}'}
        else:
            return {'code': 'print("❌ No numeric columns found")', 'explanation': 'No numeric columns'}
    
    # Head/Sample
    elif any(word in q_lower for word in ['head', 'first', 'sample', 'show rows', 'preview']):
        num = 10
        if re.search(r'\d+', question):
            num = int(re.search(r'\d+', question).group())
        code = f'''
print(f"First {num} rows:")
print("="*70)
print(df.head({num}).to_string())
'''
        return {'code': code, 'explanation': f'Showing first {num} rows'}
    
    # Info about columns
    elif any(word in q_lower for word in ['columns', 'column names', 'what columns', 'list columns']):
        code = '''
print("Dataset Columns:")
print("="*70)
for i, col in enumerate(df.columns, 1):
    dtype = df[col].dtype
    non_null = df[col].notna().sum()
    print(f"{i}. {col} ({dtype}) - {non_null}/{len(df)} non-null")
'''
        return {'code': code, 'explanation': 'Listing all columns with details'}
    
    # Default help
    else:
        code = '''
print("="*70)
print("💡 I can help you with:")
print("="*70)
print("📊 Analysis:")
print("  - 'show summary statistics'")
print("  - 'what are the top 10 values in [column]'")
print("  - 'show missing values'")
print("  - 'what is the mean of [column]'")
print("")
print("📈 Visualizations:")
print("  - 'create a histogram of [column]'")
print("  - 'show correlation heatmap'")
print("  - 'plot [column]'")
print("  - 'create box plot of [column]'")
print("")
print("🔍 Exploration:")
print("  - 'show first 10 rows'")
print("  - 'list all columns'")
print("  - 'show unique values in [column]'")
print("  - 'count values in [column]'")
print("="*70)
'''
        return {'code': code, 'explanation': 'Showing help menu'}

# Interactive chat
print("\n" + "="*70)
print("💬 Smart Data Chat")
print("="*70)
print("Ask questions about your data in natural language!")
print("Type 'help' for examples, 'quit' to exit")
print("="*70)

while True:
    try:
        question = input("\n❓ Your question: ").strip()
        
        if question.lower() in ['quit', 'exit', 'q']:
            print("\n👋 Goodbye!")
            break
        
        if not question:
            continue
        
        if question.lower() == 'help':
            question = "help"
        
        print(f"\n🤔 Processing: {question}")
        result = generate_code(question)
        
        print(f"\n💡 {result['explanation']}")
        print(f"\n📝 Executing...")
        
        try:
            exec(result['code'], {
                'df': df, 
                'pd': pd, 
                'np': np, 
                'plt': plt, 
                'sns': sns,
                'numeric_cols': numeric_cols,
                'categorical_cols': categorical_cols,
                'all_cols': all_cols
            })
            print("\n✅ Done!")
            if os.path.exists('output.png'):
                print("📊 Visualization saved as: output.png")
        except Exception as e:
            print(f"\n⚠️  Error: {e}")
            import traceback
            traceback.print_exc()
    
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        break
    except Exception as e:
        print(f"\n❌ Error: {e}")

