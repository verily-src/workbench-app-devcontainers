"""
GCP Data Characterizer with LLM — Workbench custom app.

Connect to GCP (GCS buckets, BigQuery), profile data with metrics and histograms,
and talk to your data using an LLM (API key entered in the app).
"""
import streamlit as st
import pandas as pd

from lib.data_sources import (
    load_from_gcs,
    load_from_bigquery,
    list_gcs_buckets,
    list_gcs_blobs,
    list_bigquery_datasets,
    list_bigquery_tables,
)
from lib.profiling import render_profile_ui
from lib.llm_chat import chat_with_data

st.set_page_config(
    page_title="GCP Data Characterizer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 GCP Data Characterizer with LLM")
st.caption("Connect to GCS or BigQuery → profile data → talk to your data with an LLM")

# Sidebar: LLM API key (prompted when user wants to use chat)
with st.sidebar:
    st.header("LLM (Talk to your data)")
    st.markdown(
        "Enter your **API key** when you want to use **Talk to your data**. "
        "Supports OpenAI or any OpenAI-compatible endpoint (e.g. Azure, local models)."
    )
    api_key = st.text_input(
        "API key",
        type="password",
        placeholder="sk-... or your key",
        help="Stored in session only, not persisted.",
    )
    api_base = st.text_input(
        "API base URL (optional)",
        placeholder="https://api.openai.com/v1",
        help="Leave blank for OpenAI. Set for Azure or other compatible APIs.",
    )
    model_name = st.text_input(
        "Model name",
        value="gpt-4o-mini",
        placeholder="gpt-4o-mini",
    )

# Data source selection
st.sidebar.header("Data source")
source = st.sidebar.radio("Source type", ["GCS file", "BigQuery table"], label_visibility="collapsed")

df = None
data_summary = ""
schema_and_sample = ""

if source == "GCS file":
    st.sidebar.subheader("GCS")
    try:
        buckets = list_gcs_buckets()
    except Exception as e:
        st.sidebar.error(f"Cannot list buckets: {e}. Ensure GCP credentials are available (e.g. Workbench ADC).")
        buckets = []
    bucket = st.sidebar.selectbox("Bucket", options=[""] + buckets, key="gcs_bucket")
    if bucket:
        prefix = st.sidebar.text_input("Path prefix (optional)", key="gcs_prefix")
        try:
            blobs = list_gcs_blobs(bucket, prefix=prefix)
        except Exception as e:
            st.sidebar.error(str(e))
            blobs = []
        blob_path = st.sidebar.selectbox("File path", options=[""] + blobs[:200], key="gcs_blob")
        file_format = st.sidebar.selectbox("Format", ["csv", "parquet", "json"], key="gcs_fmt")
        if st.sidebar.button("Load from GCS") and blob_path:
            with st.spinner("Loading from GCS..."):
                try:
                    df = load_from_gcs(bucket, blob_path, file_format)
                    st.sidebar.success(f"Loaded {len(df):,} rows × {len(df.columns)} columns")
                except Exception as e:
                    st.sidebar.error(str(e))

elif source == "BigQuery table":
    st.sidebar.subheader("BigQuery")
    project = st.sidebar.text_input("Project ID", key="bq_project", placeholder="your-gcp-project")
    if project:
        try:
            datasets = list_bigquery_datasets(project)
        except Exception as e:
            st.sidebar.error(f"Cannot list datasets: {e}")
            datasets = []
        dataset = st.sidebar.selectbox("Dataset", options=[""] + datasets, key="bq_dataset")
        if dataset:
            try:
                tables = list_bigquery_tables(project, dataset)
            except Exception as e:
                st.sidebar.error(str(e))
                tables = []
            table = st.sidebar.selectbox("Table", options=[""] + tables, key="bq_table")
            limit = st.sidebar.number_input("Max rows", min_value=1000, value=50_000, step=10_000)
            if st.sidebar.button("Load from BigQuery") and table:
                with st.spinner("Loading from BigQuery..."):
                    try:
                        df = load_from_bigquery(project, dataset, table, limit=limit)
                        st.sidebar.success(f"Loaded {len(df):,} rows × {len(df.columns)} columns")
                    except Exception as e:
                        st.sidebar.error(str(e))

# Store dataframe in session for chat
if df is not None and not df.empty:
    st.session_state["df"] = df
    data_summary = f"Rows: {len(df):,}, Columns: {len(df.columns)}. Column names: {list(df.columns)}."
    schema_and_sample = f"dtypes:\n{df.dtypes.to_string()}\n\nSample (first 20 rows):\n{df.head(20).to_string()}"

if "df" in st.session_state:
    df = st.session_state["df"]
    data_summary = f"Rows: {len(df):,}, Columns: {len(df.columns)}. Column names: {list(df.columns)}."
    schema_and_sample = f"dtypes:\n{df.dtypes.to_string()}\n\nSample (first 20 rows):\n{df.head(20).to_string()}"

# Tabs: Overview, Profile, Talk to your data
if df is not None and not df.empty:
    tab1, tab2, tab3 = st.tabs(["Overview", "Data profiling & histograms", "Talk to your data"])

    with tab1:
        st.subheader("Data preview")
        st.dataframe(df.head(100), use_container_width=True, hide_index=True)
        st.write(f"Total rows: {len(df):,}")

    with tab2:
        render_profile_ui(df)

    with tab3:
        st.subheader("Talk to your data")
        st.markdown("Ask questions about the loaded dataset. The LLM uses the schema and a sample of the data.")
        if not api_key:
            st.info("👆 Enter your LLM API key in the sidebar to enable chat.")
        prompt = st.chat_input("Ask a question about the data...")
        if "chat_messages" not in st.session_state:
            st.session_state["chat_messages"] = []

        for msg in st.session_state["chat_messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt:
            st.session_state["chat_messages"].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                reply, _ = chat_with_data(
                    api_key=api_key or "",
                    base_url=api_base or None,
                    model=model_name or "gpt-4o-mini",
                    data_summary=data_summary,
                    schema_and_sample=schema_and_sample,
                    question=prompt,
                    conversation=st.session_state["chat_messages"][:-1],
                )
                st.markdown(reply)
                st.session_state["chat_messages"].append({"role": "assistant", "content": reply})
else:
    st.info(
        "👈 Select a **data source** in the sidebar (GCS file or BigQuery table) and load data to start profiling and talking to your data."
    )
