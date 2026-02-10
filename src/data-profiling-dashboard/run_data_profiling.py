#!/usr/bin/env python3
"""
Data Profiling Dashboard - Run this script to load data from GCS and generate a profiling report.
Use in any Workbench workspace: set GCS_BUCKET and FILE_NAME below for this workspace's data collection.
Double-click to run, or: python run_data_profiling.py
"""

import pandas as pd
import numpy as np
import os
import sys
import subprocess
from pathlib import Path

# ============================================================================
# CONFIGURATION: Set these for your workspace's data collection
# ============================================================================
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"  # Your data collection bucket
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"   # Your data file
FILE_FORMAT = "csv"  # csv, parquet, json, excel

print("="*70)
print("Data Profiling Dashboard")
print("="*70)
print(f"Bucket: {GCS_BUCKET}")
print(f"File: {FILE_NAME}")
print(f"GCS Path: gs://{GCS_BUCKET}/{FILE_NAME}")
print("="*70)

# Install google-cloud-storage if needed
try:
    from google.cloud import storage
except ImportError:
    print("Installing google-cloud-storage...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-storage"])
    from google.cloud import storage

# Install ydata-profiling if needed
try:
    from ydata_profiling import ProfileReport
except ImportError:
    print("Installing ydata-profiling...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "ydata-profiling"])
    from ydata_profiling import ProfileReport

# Compatibility patch for numpy/wordcloud
original_asarray = np.asarray
def patched_asarray(a, dtype=None, order=None, copy=None, **kwargs):
    try:
        if copy is not None:
            return original_asarray(a, dtype=dtype, order=order, copy=copy, **kwargs)
        return original_asarray(a, dtype=dtype, order=order, **kwargs)
    except TypeError:
        if "copy" in kwargs:
            kwargs.pop("copy")
        return original_asarray(a, dtype=dtype, order=order, **kwargs)
np.asarray = patched_asarray

try:
    import ydata_profiling.visualisation.plot as plot_module
    def noop_plot_word_cloud(config, word_counts):
        return ""
    plot_module.plot_word_cloud = noop_plot_word_cloud
    if hasattr(plot_module, "_plot_word_cloud"):
        plot_module._plot_word_cloud = lambda config, series, figsize=None: None
except Exception:
    pass

# ============================================================================
# Load data from GCS
# ============================================================================
def load_data_from_gcs(bucket_name, file_name, file_format="csv"):
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

bucket_name = GCS_BUCKET.replace("gs://", "").strip()
print("\nLoading data from GCS...")
df = load_data_from_gcs(bucket_name, FILE_NAME, FILE_FORMAT)
print(f"Loaded: {len(df)} rows, {len(df.columns)} columns")
print(df.head(10))

# ============================================================================
# Generate profiling report
# ============================================================================
print("\nGenerating data profiling report...")
profile = ProfileReport(df, title="Data Profiling Report", explorative=True, minimal=False, progress_bar=True)
report_file = "data_profile_report.html"
profile.to_file(report_file)
report_path = os.path.abspath(report_file)
print(f"Report saved: {report_path}")

try:
    import webbrowser
    webbrowser.open(f"file://{report_path}")
except Exception:
    print(f"Open manually: {report_path}")

print("\nDone.")
