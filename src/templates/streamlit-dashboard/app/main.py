#!/usr/bin/env python3
"""
Streamlit Dashboard Template for Verily Workbench

Interactive data visualization with workspace resource integration.
"""

import os
import streamlit as st
import pandas as pd
from google.cloud import storage, bigquery

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Workbench Dashboard",
    page_icon="📊",
    layout="wide"
)

# =============================================================================
# WORKSPACE HELPERS
# =============================================================================

@st.cache_resource
def get_gcs_client():
    return storage.Client()

@st.cache_resource
def get_bq_client():
    return bigquery.Client()

def get_workspace_resources():
    """Get all WORKBENCH_ environment variables."""
    return {
        k.replace("WORKBENCH_", ""): v 
        for k, v in os.environ.items() 
        if k.startswith("WORKBENCH_")
    }

# =============================================================================
# SIDEBAR: RESOURCE BROWSER
# =============================================================================

st.sidebar.title("🗂️ Workspace Resources")

resources = get_workspace_resources()
if resources:
    st.sidebar.markdown("**Available Resources:**")
    for name, path in resources.items():
        st.sidebar.code(f"{name}: {path}")
else:
    st.sidebar.info("No workspace resources found")

# =============================================================================
# MAIN CONTENT
# =============================================================================

st.title("📊 Data Dashboard")
st.markdown("Interactive data exploration for your Workbench workspace")

# Tabs for different data sources
tab1, tab2, tab3 = st.tabs(["📁 GCS Files", "📊 BigQuery", "📈 Visualize"])

# -----------------------------------------------------------------------------
# TAB 1: GCS FILE BROWSER
# -----------------------------------------------------------------------------

with tab1:
    st.header("Cloud Storage Browser")
    
    # Get buckets from workspace resources
    buckets = [v for k, v in resources.items() if v.startswith("gs://")]
    
    if buckets:
        selected_bucket = st.selectbox("Select Bucket", buckets)
        
        if selected_bucket:
            bucket_name = selected_bucket.replace("gs://", "")
            
            try:
                client = get_gcs_client()
                bucket = client.bucket(bucket_name)
                blobs = list(bucket.list_blobs(max_results=100))
                
                if blobs:
                    files_df = pd.DataFrame([
                        {"Name": b.name, "Size (KB)": b.size / 1024, "Updated": b.updated}
                        for b in blobs
                    ])
                    st.dataframe(files_df, use_container_width=True)
                    
                    # File preview
                    csv_files = [b.name for b in blobs if b.name.endswith('.csv')]
                    if csv_files:
                        selected_file = st.selectbox("Preview CSV", csv_files)
                        if st.button("Load File"):
                            blob = bucket.blob(selected_file)
                            data = blob.download_as_text()
                            df = pd.read_csv(pd.io.common.StringIO(data))
                            st.dataframe(df.head(100))
                else:
                    st.info("Bucket is empty")
            except Exception as e:
                st.error(f"Error accessing bucket: {e}")
    else:
        st.info("No GCS buckets found in workspace resources")

# -----------------------------------------------------------------------------
# TAB 2: BIGQUERY EXPLORER
# -----------------------------------------------------------------------------

with tab2:
    st.header("BigQuery Explorer")
    
    query = st.text_area(
        "Enter SQL Query",
        value="SELECT * FROM `your-project.your-dataset.your-table` LIMIT 100",
        height=150
    )
    
    if st.button("Run Query"):
        try:
            client = get_bq_client()
            with st.spinner("Running query..."):
                df = client.query(query).to_dataframe()
            
            st.success(f"Query returned {len(df)} rows")
            st.dataframe(df, use_container_width=True)
            
            # Store in session state for visualization
            st.session_state["query_result"] = df
        except Exception as e:
            st.error(f"Query error: {e}")

# -----------------------------------------------------------------------------
# TAB 3: VISUALIZATION
# -----------------------------------------------------------------------------

with tab3:
    st.header("Data Visualization")
    
    # File uploader for local CSV
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
    
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        st.session_state["viz_data"] = df
    
    # Use query results or uploaded data
    if "viz_data" in st.session_state:
        df = st.session_state["viz_data"]
    elif "query_result" in st.session_state:
        df = st.session_state["query_result"]
    else:
        st.info("Upload a CSV or run a BigQuery query to visualize data")
        st.stop()
    
    # Column selection
    col1, col2 = st.columns(2)
    with col1:
        x_col = st.selectbox("X Axis", df.columns)
    with col2:
        y_col = st.selectbox("Y Axis", [c for c in df.columns if c != x_col])
    
    chart_type = st.radio("Chart Type", ["Line", "Bar", "Scatter"], horizontal=True)
    
    # Create chart
    if chart_type == "Line":
        st.line_chart(df.set_index(x_col)[y_col])
    elif chart_type == "Bar":
        st.bar_chart(df.set_index(x_col)[y_col])
    else:
        st.scatter_chart(df, x=x_col, y=y_col)

# =============================================================================
# FOOTER
# =============================================================================

st.markdown("---")
st.caption("Powered by Streamlit | Verily Workbench")
