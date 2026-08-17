#!/usr/bin/env python3
"""
Simple BigQuery SQL Query Executor
Execute SQL queries against your Workbench datasets
"""

import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.auth import default
import re

# Page configuration
st.set_page_config(
    page_title="SQL Query Executor",
    page_icon="🔍",
    layout="wide"
)

# Initialize BigQuery client
@st.cache_resource
def get_bigquery_client():
    """Initialize and cache BigQuery client"""
    try:
        credentials, project = default()
        client = bigquery.Client(credentials=credentials, project=project)
        return client, project
    except Exception as e:
        st.error(f"Failed to initialize BigQuery client: {e}")
        return None, None

def execute_query(client, query):
    """Execute a SQL query and return results as DataFrame"""
    try:
        # Run the query
        query_job = client.query(query)

        # Get results
        results = query_job.result()
        df = results.to_dataframe()

        # Get query stats
        stats = {
            "bytes_processed": query_job.total_bytes_processed,
            "bytes_billed": query_job.total_bytes_billed,
            "slot_time": query_job.slot_millis,
            "rows_returned": len(df)
        }

        return df, stats, None
    except Exception as e:
        return None, None, str(e)

def format_bytes(bytes_val):
    """Format bytes to human-readable format"""
    if bytes_val == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes_val >= 1024 and i < len(units) - 1:
        bytes_val /= 1024.0
        i += 1

    return f"{bytes_val:.2f} {units[i]}"

# Main app
def main():
    st.title("🔍 SQL Query Executor")
    st.markdown("Execute SQL queries against BigQuery datasets in your Workbench workspace")

    # Initialize client
    client, project = get_bigquery_client()

    if not client:
        st.error("Cannot connect to BigQuery. Please check your credentials.")
        return

    st.success(f"Connected to project: **{project}**")

    # Sidebar with help
    with st.sidebar:
        st.header("Quick Help")

        st.markdown("### Query Format")
        st.code("""
SELECT *
FROM `project.dataset.table`
LIMIT 100
        """, language="sql")

        st.markdown("### Your Project")
        st.info(f"**{project}**")

        st.markdown("### Tips")
        st.markdown("""
- Use backticks `` for table names
- Include LIMIT to avoid large results
- Use fully qualified names:
  `project.dataset.table`
- Press Ctrl+Enter to execute
        """)

        st.markdown("### Examples")

        if st.button("📊 List All Datasets"):
            st.session_state['query'] = f"""
SELECT schema_name as dataset
FROM `{project}.INFORMATION_SCHEMA.SCHEMATA`
ORDER BY schema_name
            """.strip()

        if st.button("📋 Show Dataset Tables"):
            st.session_state['query'] = f"""
SELECT
  table_schema as dataset,
  table_name,
  table_type,
  TIMESTAMP_MILLIS(creation_time) as created,
  row_count,
  size_bytes
FROM `{project}.__TABLES__`
ORDER BY table_schema, table_name
            """.strip()

    # Main query area
    st.header("SQL Query")

    # Get query from session state or default
    default_query = st.session_state.get('query', f"""
SELECT *
FROM `{project}.DATASET.TABLE`
LIMIT 100
    """.strip())

    query = st.text_area(
        "Enter your SQL query:",
        value=default_query,
        height=200,
        key="sql_input"
    )

    # Store query in session state
    st.session_state['query'] = query

    col1, col2, col3 = st.columns([1, 1, 4])

    with col1:
        execute_button = st.button("▶️ Execute Query", type="primary", use_container_width=True)

    with col2:
        if st.button("🗑️ Clear", use_container_width=True):
            st.session_state['query'] = ""
            st.rerun()

    # Execute query
    if execute_button and query.strip():
        with st.spinner("Executing query..."):
            df, stats, error = execute_query(client, query)

            if error:
                st.error(f"Query failed: {error}")
            else:
                # Show stats
                st.subheader("Query Statistics")
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("Rows Returned", f"{stats['rows_returned']:,}")

                with col2:
                    st.metric("Bytes Processed", format_bytes(stats['bytes_processed']))

                with col3:
                    st.metric("Bytes Billed", format_bytes(stats['bytes_billed']))

                with col4:
                    slot_seconds = stats['slot_time'] / 1000.0
                    st.metric("Slot Time", f"{slot_seconds:.2f}s")

                # Show results
                st.subheader("Query Results")

                if len(df) > 0:
                    # Display dataframe
                    st.dataframe(df, use_container_width=True, height=400)

                    # Download button
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv,
                        file_name="query_results.csv",
                        mime="text/csv"
                    )

                    # Show schema
                    with st.expander("📋 Show Schema"):
                        schema_df = pd.DataFrame({
                            "Column": df.columns,
                            "Type": [str(dtype) for dtype in df.dtypes],
                            "Sample": [df[col].iloc[0] if len(df) > 0 else None for col in df.columns]
                        })
                        st.dataframe(schema_df, use_container_width=True)
                else:
                    st.info("Query executed successfully but returned no rows.")

    elif execute_button:
        st.warning("Please enter a SQL query.")

    # Query history (simple version)
    st.markdown("---")

    with st.expander("ℹ️ About"):
        st.markdown("""
        ### BigQuery SQL Query Executor

        This app allows you to execute SQL queries against BigQuery datasets in your Workbench workspace.

        **Features:**
        - Execute any SELECT query
        - View query statistics (bytes processed, slot time)
        - Download results as CSV
        - View schema information

        **Supported:**
        - All standard SQL queries
        - Queries across datasets and projects
        - JOIN operations
        - Aggregations and GROUP BY
        - CTEs (WITH clauses)

        **Authentication:**
        Uses Google Cloud Application Default Credentials configured by Workbench.
        """)

if __name__ == "__main__":
    main()
