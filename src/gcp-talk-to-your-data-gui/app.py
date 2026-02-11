"""
Streamlit GUI: GCP data discovery, load, and Talk to your data (LLM).
Uses gcp_tools for GCS/BigQuery and OpenAI (US endpoint supported for company keys).
Optional env: OPENAI_SECRET_PROJECT, OPENAI_SECRET_NAME, OPENAI_SECRET_VERSION → auto-fetch key on load.
"""
import os
import streamlit as st
import pandas as pd

from gcp_tools import (
    get_default_project,
    list_gcs_buckets,
    list_gcs_blobs,
    load_from_gcs,
    list_bigquery_datasets,
    list_bigquery_tables,
    load_from_bigquery,
    get_openai_key_by_secret_name,
    data_summary_for_llm,
    talk_to_data,
    OPENAI_US_BASE_URL,
)

st.set_page_config(page_title="Talk to your GCP data", layout="wide")

# Session state
if "df" not in st.session_state:
    st.session_state.df = None
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "data_summary" not in st.session_state:
    st.session_state.data_summary = ""
if "schema_and_sample" not in st.session_state:
    st.session_state.schema_and_sample = ""
if "api_key_auto_fetched" not in st.session_state:
    st.session_state.api_key_auto_fetched = False
if "api_key_from_auto_fetch" not in st.session_state:
    st.session_state.api_key_from_auto_fetch = False

# Auto-fetch key from Secret Manager once per session when env is set
if not st.session_state.api_key and not st.session_state.api_key_auto_fetched:
    st.session_state.api_key_auto_fetched = True
    _project = os.environ.get("OPENAI_SECRET_PROJECT", "").strip()
    _secret = os.environ.get("OPENAI_SECRET_NAME", "").strip()
    _version = os.environ.get("OPENAI_SECRET_VERSION", "latest").strip() or "latest"
    if _project and _secret:
        try:
            st.session_state.api_key = get_openai_key_by_secret_name(_project, _secret, _version)
            st.session_state.api_key_from_auto_fetch = True
        except Exception:
            pass  # Leave key empty; user can paste or fetch manually

def ensure_data_context():
    if st.session_state.df is not None and not st.session_state.data_summary:
        st.session_state.data_summary, st.session_state.schema_and_sample = data_summary_for_llm(
            st.session_state.df
        )

# Sidebar: API key and data source
with st.sidebar:
    st.header("API key")
    if st.session_state.api_key_from_auto_fetch:
        st.caption("Key loaded from Secret Manager (auto-fetch)")
    key_source = st.radio("Key from", ["Paste key", "Secret Manager"], horizontal=True)
    if key_source == "Paste key":
        st.session_state.api_key = st.text_input(
            "OpenAI API key", type="password", value=st.session_state.api_key, key="api_key_input"
        )
    else:
        sm_project = st.text_input("GCP project (e.g. wb-smart-cabbage-5940)", key="sm_project")
        sm_secret = st.text_input("Secret name (e.g. si-ops-openai-api-key)", key="sm_secret")
        sm_version = st.text_input("Version", value="latest", key="sm_version")
        if st.button("Fetch key from Secret Manager"):
            if sm_project and sm_secret:
                try:
                    st.session_state.api_key = get_openai_key_by_secret_name(
                        sm_project, sm_secret, sm_version or "latest"
                    )
                    st.success("Key loaded")
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("Enter project and secret name")
    use_us_endpoint = st.checkbox("Use US endpoint (company keys)", value=True, key="us_endpoint")

    st.divider()
    st.header("Data source")
    source = st.radio("Source", ["GCS", "BigQuery"], key="source")

    default_project = get_default_project() or ""

    if source == "GCS":
        project = st.text_input("GCP project (optional)", value=default_project, key="gcs_project")
        buckets = []
        if project:
            try:
                buckets = list_gcs_buckets(project or None)
            except Exception as e:
                st.error(str(e))
        bucket = st.selectbox("Bucket", [""] + buckets, key="gcs_bucket") if buckets else st.text_input("Bucket name", key="gcs_bucket")
        prefix = st.text_input("Prefix (optional)", key="gcs_prefix")
        blobs = []
        if bucket:
            try:
                blobs = list_gcs_blobs(bucket, prefix)
            except Exception as e:
                st.error(str(e))
        gcs_path = st.selectbox("File path", [""] + blobs[:200], key="gcs_path") if blobs else st.text_input("Blob path", key="gcs_path")
        fmt = st.selectbox("Format", ["csv", "parquet", "json"], key="gcs_fmt")
        if st.button("Load from GCS"):
            if bucket and gcs_path:
                try:
                    st.session_state.df = load_from_gcs(bucket, gcs_path, fmt)
                    st.session_state.data_summary = ""
                    st.session_state.schema_and_sample = ""
                    ensure_data_context()
                    st.success(f"Loaded {len(st.session_state.df):,} rows")
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("Select bucket and path")

    else:
        project = st.text_input("GCP project", value=default_project, key="bq_project")
        datasets = []
        if project:
            try:
                datasets = list_bigquery_datasets(project)
            except Exception as e:
                st.error(str(e))
        dataset = st.selectbox("Dataset", [""] + datasets, key="bq_dataset")
        tables = []
        if project and dataset:
            try:
                tables = list_bigquery_tables(project, dataset)
            except Exception as e:
                st.error(str(e))
        table = st.selectbox("Table", [""] + tables, key="bq_table")
        limit = st.number_input("Row limit", min_value=100, value=10_000, step=1000, key="bq_limit")
        if st.button("Load from BigQuery"):
            if project and dataset and table:
                try:
                    st.session_state.df = load_from_bigquery(project, dataset, table, int(limit))
                    st.session_state.data_summary = ""
                    st.session_state.schema_and_sample = ""
                    ensure_data_context()
                    st.success(f"Loaded {len(st.session_state.df):,} rows")
                except Exception as e:
                    st.error(str(e))
            else:
                st.warning("Select project, dataset, and table")

# Main area
st.title("Talk to your GCP data")

if st.session_state.df is not None:
    ensure_data_context()
    st.subheader("Data preview")
    st.dataframe(st.session_state.df.head(100), use_container_width=True)

    st.subheader("Ask a question")
    question = st.text_area("Question about the data", height=100, key="question")
    model = st.text_input("Model", value="gpt-4o-mini", key="model")
    if st.button("Ask"):
        if not question.strip():
            st.warning("Enter a question")
        elif not st.session_state.api_key:
            st.warning("Set your API key in the sidebar")
        else:
            base = OPENAI_US_BASE_URL if use_us_endpoint else None
            with st.spinner("Asking..."):
                answer = talk_to_data(
                    st.session_state.api_key,
                    st.session_state.data_summary,
                    st.session_state.schema_and_sample,
                    question,
                    model=model,
                    base_url=base,
                )
            st.markdown(answer)
else:
    st.info("Load a dataset from the sidebar (GCS or BigQuery) to start. Then set your API key and ask questions.")
