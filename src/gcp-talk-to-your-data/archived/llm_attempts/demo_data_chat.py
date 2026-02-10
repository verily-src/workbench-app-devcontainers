#!/usr/bin/env python3
"""
Demo Data Chat - Interactive data analysis tool
Talk to your CSV file and get instant analysis with charts and metrics.
Perfect for demos - works immediately, no setup required.
"""

import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import re
from pathlib import Path

# Set style for better-looking plots
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

print("="*70)
print("🤖 Demo Data Chat - Interactive Data Analysis")
print("="*70)

# Get CSV file name
if len(sys.argv) > 1:
    csv_file = sys.argv[1]
else:
    csv_file = input("\n📁 Enter CSV file path (or press Enter for default): ").strip()
    if not csv_file:
        # Look for CSV files in current directory
        csv_files = list(Path('.').glob('*.csv'))
        if csv_files:
            print(f"\nFound CSV files:")
            for i, f in enumerate(csv_files, 1):
                print(f"  {i}. {f}")
            choice = input(f"\nSelect file number (1-{len(csv_files)}) or enter path: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(csv_files):
                csv_file = str(csv_files[int(choice)-1])
            else:
                csv_file = choice if choice else csv_files[0]
        else:
            print("❌ No CSV files found. Please provide a file path.")
            sys.exit(1)

# Load data
print(f"\n📥 Loading data from: {csv_file}")
try:
    if not os.path.exists(csv_file):
        print(f"❌ File not found: {csv_file}")
        sys.exit(1)
    
    df = pd.read_csv(csv_file)
    print(f"✅ Data loaded: {len(df)} rows × {len(df.columns)} columns")
    print(f"📋 Columns: {', '.join(df.columns)}")
except Exception as e:
    print(f"❌ Error loading file: {e}")
    sys.exit(1)

# Get column info
numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
all_cols = list(df.columns)

def find_column(question, columns):
    """Find column mentioned in question."""
    q_lower = question.lower()
    for col in columns:
        if col.lower() in q_lower:
            return col
    return None

def generate_analysis(question):
    """Generate analysis code based on question."""
    q_lower = question.lower()
    
    # Comprehensive summary
    if any(w in q_lower for w in ['summary', 'overview', 'characterize', 'characteristics', 'describe']):
        return {
            'code': '''
print("="*70)
print("📊 COMPREHENSIVE DATA CHARACTERIZATION")
print("="*70)
print(f"\\n📏 Dataset Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")
print(f"💾 Memory Usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
print(f"\\n📋 Columns ({len(df.columns)}):")
for i, col in enumerate(df.columns, 1):
    dtype = str(df[col].dtype)
    non_null = df[col].notna().sum()
    pct = (non_null / len(df)) * 100
    print(f"  {i:2d}. {col:30s} ({dtype:10s}) - {non_null:6,}/{len(df):,} ({pct:5.1f}%) non-null")

if numeric_cols:
    print(f"\\n📈 Numeric Columns Summary:")
    print(df[numeric_cols].describe().to_string())
    
    print(f"\\n📊 Numeric Column Statistics:")
    for col in numeric_cols:
        print(f"\\n  {col}:")
        print(f"    Mean:   {df[col].mean():.2f}")
        print(f"    Median: {df[col].median():.2f}")
        print(f"    Std:    {df[col].std():.2f}")
        print(f"    Min:    {df[col].min():.2f}")
        print(f"    Max:    {df[col].max():.2f}")
        print(f"    Range:  {df[col].max() - df[col].min():.2f}")

if categorical_cols:
    print(f"\\n📝 Categorical Columns Summary:")
    for col in categorical_cols:
        print(f"\\n  {col}:")
        print(f"    Unique values: {df[col].nunique()}")
        print(f"    Most common: {df[col].value_counts().head(3).to_dict()}")

missing = df.isnull().sum()
if missing.sum() > 0:
    print(f"\\n⚠️  Missing Values:")
    missing_df = pd.DataFrame({
        'Column': missing.index,
        'Missing': missing.values,
        'Percentage': (missing.values / len(df) * 100).round(2)
    })
    missing_df = missing_df[missing_df['Missing'] > 0].sort_values('Missing', ascending=False)
    print(missing_df.to_string(index=False))
else:
    print(f"\\n✅ No missing values found!")
print("="*70)
''',
            'explanation': 'Comprehensive data characterization report'
        }
    
    # Histogram
    elif any(w in q_lower for w in ['histogram', 'distribution', 'dist', 'hist']):
        col = find_column(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            return {
                'code': f'''
fig, axes = plt.subplots(1, 2, figsize=(16, 6))

# Histogram
axes[0].hist(df["{col}"].dropna(), bins=30, edgecolor='black', alpha=0.7, color='steelblue')
axes[0].set_title(f"Distribution of {col}", fontsize=14, fontweight='bold')
axes[0].set_xlabel("{col}", fontsize=12)
axes[0].set_ylabel("Frequency", fontsize=12)
axes[0].axvline(df["{col}"].mean(), color='red', linestyle='--', linewidth=2, label=f'Mean: {{df["{col}"].mean():.2f}}')
axes[0].axvline(df["{col}"].median(), color='green', linestyle='--', linewidth=2, label=f'Median: {{df["{col}"].median():.2f}}')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Box plot
axes[1].boxplot(df["{col}"].dropna(), vert=True, patch_artist=True,
                boxprops=dict(facecolor='lightblue', alpha=0.7))
axes[1].set_title(f"Box Plot of {col}", fontsize=14, fontweight='bold')
axes[1].set_ylabel("{col}", fontsize=12)
axes[1].grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print(f"✅ Distribution analysis for '{col}' saved as output.png")
''',
                'explanation': f'Creating distribution histogram and box plot for {col}'
            }
        return {'code': 'print("❌ No numeric columns for histogram")', 'explanation': 'No numeric columns'}
    
    # Correlation heatmap
    elif any(w in q_lower for w in ['correlation', 'correlate', 'heatmap', 'corr']):
        if len(numeric_cols) > 1:
            return {
                'code': '''
plt.figure(figsize=(12, 10))
corr = df[numeric_cols].corr()
mask = np.triu(np.ones_like(corr, dtype=bool))
sns.heatmap(corr, mask=mask, annot=True, fmt='.2f', cmap='coolwarm', center=0,
            square=True, linewidths=1, cbar_kws={"shrink": 0.8}, vmin=-1, vmax=1)
plt.title("Correlation Heatmap", fontsize=16, fontweight='bold', pad=20)
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print("✅ Correlation heatmap saved as output.png")
''',
                'explanation': 'Creating correlation heatmap of numeric columns'
            }
        return {'code': 'print("❌ Need at least 2 numeric columns")', 'explanation': 'Not enough numeric columns'}
    
    # Top values
    elif any(w in q_lower for w in ['top', 'highest', 'maximum', 'max', 'largest']):
        col = find_column(question, all_cols) or all_cols[0]
        num = 10
        if re.search(r'\d+', question):
            num = int(re.search(r'\d+', question).group())
        return {
            'code': f'''
print(f"Top {num} values in '{col}':")
print("="*70)
if col in numeric_cols:
    top = df.nlargest({num}, col)[[col]]
    print(top.to_string())
    print(f"\\nStatistics:")
    print(f"  Mean: {{df[col].mean():.2f}}")
    print(f"  Median: {{df[col].median():.2f}}")
else:
    counts = df[col].value_counts().head({num})
    print(counts.to_string())
    print(f"\\nTotal unique: {{df[col].nunique()}}")
print("="*70)
''',
            'explanation': f'Showing top {num} values in {col}'
        }
    
    # Missing values
    elif any(w in q_lower for w in ['missing', 'null', 'na', 'empty']):
        return {
            'code': '''
missing = df.isnull().sum()
if missing.sum() > 0:
    missing_df = pd.DataFrame({
        'Column': missing.index,
        'Missing Count': missing.values,
        'Missing %': (missing.values / len(df) * 100).round(2)
    })
    missing_df = missing_df[missing_df['Missing Count'] > 0].sort_values('Missing Count', ascending=False)
    print("Missing Values Analysis:")
    print("="*70)
    print(missing_df.to_string(index=False))
    print(f"\\nTotal missing values: {missing.sum():,}")
else:
    print("✅ No missing values found in the dataset!")
''',
            'explanation': 'Analyzing missing values'
        }
    
    # Unique values
    elif any(w in q_lower for w in ['unique', 'distinct', 'different']):
        col = find_column(question, all_cols)
        if col:
            return {
                'code': f'''
print(f"Unique Values Analysis for '{col}':")
print("="*70)
print(f"Total unique values: {{df['{col}'].nunique()}}")
print(f"Total rows: {{len(df)}}")
print(f"\\nValue counts (top 20):")
print(df['{col}'].value_counts().head(20).to_string())
print("="*70)
''',
                'explanation': f'Showing unique values in {col}'
            }
        return {
            'code': '''
print("Unique Value Counts per Column:")
print("="*70)
for col in df.columns:
    print(f"{col:30s}: {df[col].nunique():6,} unique values")
print("="*70)
''',
            'explanation': 'Showing unique value counts for all columns'
        }
    
    # Plot/visualize
    elif any(w in q_lower for w in ['plot', 'chart', 'graph', 'visualize']):
        col = find_column(question, numeric_cols) or (numeric_cols[0] if numeric_cols else None)
        if col:
            return {
                'code': f'''
plt.figure(figsize=(12, 6))
df["{col}"].plot(kind='line', linewidth=2, color='steelblue')
plt.title(f"{col} over Index", fontsize=14, fontweight='bold')
plt.xlabel("Index", fontsize=12)
plt.ylabel("{col}", fontsize=12)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("output.png", dpi=150, bbox_inches='tight')
plt.show()
print(f"✅ Plot saved as output.png")
''',
                'explanation': f'Plotting {col}'
            }
        return {'code': 'print("❌ No numeric columns to plot")', 'explanation': 'No numeric columns'}
    
    # Help
    else:
        return {
            'code': '''
print("="*70)
print("💡 Available Commands:")
print("="*70)
print("📊 Analysis:")
print("  • 'show summary' or 'characterize data'")
print("  • 'show missing values'")
print("  • 'show unique values in [column]'")
print("")
print("📈 Visualizations:")
print("  • 'create histogram' or 'show distribution'")
print("  • 'create correlation heatmap'")
print("  • 'plot [column name]'")
print("")
print("🔍 Exploration:")
print("  • 'show top 10 values in [column]'")
print("  • 'list columns'")
print("="*70)
''',
            'explanation': 'Showing help menu'
        }

# Main interactive loop
print("\n" + "="*70)
print("💬 Interactive Data Chat")
print("="*70)
print("Ask questions about your data! Type 'help' for examples, 'quit' to exit")
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
        result = generate_analysis(question)
        
        print(f"💡 {result['explanation']}")
        print(f"📝 Executing...\n")
        
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

