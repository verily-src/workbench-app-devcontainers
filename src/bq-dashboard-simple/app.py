#!/usr/bin/env python3
"""
BigQuery Monitoring Dashboard
Real-time monitoring of BigQuery datasets with data profiling
"""

import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.auth import default
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
from ydata_profiling import ProfileReport
import streamlit.components.v1 as components
import tempfile
import os

# Page configuration
st.set_page_config(
    page_title="BigQuery Monitoring Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
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

# Get all datasets in the project
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_datasets(project):
    """Fetch all datasets in the project"""
    try:
        client, _ = get_bigquery_client()
        if not client:
            return []

        datasets = list(client.list_datasets())
        return [dataset.dataset_id for dataset in datasets]
    except Exception as e:
        st.error(f"Error fetching datasets: {e}")
        return []

# Get all tables in a dataset
@st.cache_data(ttl=300)
def get_tables(project, dataset_id):
    """Fetch all tables in a dataset"""
    try:
        client, _ = get_bigquery_client()
        if not client:
            return []

        tables = list(client.list_tables(dataset_id))
        return [table.table_id for table in tables]
    except Exception as e:
        st.error(f"Error fetching tables: {e}")
        return []

# Get table metadata
@st.cache_data(ttl=60)  # Cache for 1 minute
def get_table_info(project, dataset_id, table_id):
    """Get table metadata including row count and last modified"""
    try:
        client, _ = get_bigquery_client()
        if not client:
            return None

        table_ref = f"{project}.{dataset_id}.{table_id}"
        table = client.get_table(table_ref)

        return {
            "table_id": table_id,
            "num_rows": table.num_rows,
            "num_bytes": table.num_bytes,
            "created": table.created,
            "modified": table.modified,
            "schema_fields": len(table.schema),
            "table_type": table.table_type
        }
    except Exception as e:
        st.error(f"Error fetching table info: {e}")
        return None

# Query table data
@st.cache_data(ttl=60)
def query_table_sample(project, dataset_id, table_id, limit=100):
    """Query sample data from table"""
    try:
        client, _ = get_bigquery_client()
        if not client:
            return None

        query = f"""
        SELECT *
        FROM `{project}.{dataset_id}.{table_id}`
        LIMIT {limit}
        """

        df = client.query(query).to_dataframe()
        return df
    except Exception as e:
        st.error(f"Error querying table: {e}")
        return None

# Query for time-based metrics (if timestamp column exists)
@st.cache_data(ttl=60)
def get_time_series_data(project, dataset_id, table_id, time_column=None):
    """Get time series data for visualization"""
    try:
        client, _ = get_bigquery_client()
        if not client:
            return None

        # Try to find a timestamp column if not provided
        if not time_column:
            table_ref = f"{project}.{dataset_id}.{table_id}"
            table = client.get_table(table_ref)

            # Look for common timestamp column names
            time_columns = [field.name for field in table.schema
                          if field.field_type in ['TIMESTAMP', 'DATE', 'DATETIME']]

            if not time_columns:
                return None

            time_column = time_columns[0]

        query = f"""
        SELECT
            DATE({time_column}) as date,
            COUNT(*) as count
        FROM `{project}.{dataset_id}.{table_id}`
        WHERE {time_column} IS NOT NULL
        GROUP BY date
        ORDER BY date DESC
        LIMIT 365
        """

        df = client.query(query).to_dataframe()
        return df, time_column
    except Exception as e:
        # Silently fail if no time column exists
        return None

# Generate profiling report
def generate_profiling_report(df, title="Data Profile"):
    """Generate ydata-profiling report"""
    try:
        with st.spinner("Generating detailed data profile... This may take a moment."):
            # Limit rows for profiling to prevent timeout
            df_sample = df.head(10000) if len(df) > 10000 else df

            profile = ProfileReport(
                df_sample,
                title=title,
                minimal=False,
                explorative=True,
                progress_bar=False
            )

            return profile
    except Exception as e:
        st.error(f"Error generating profile: {e}")
        return None

# Main dashboard
def main():
    st.title("📊 BigQuery Monitoring Dashboard")
    st.markdown("Real-time monitoring of BigQuery datasets with detailed data profiling")

    # Initialize client
    client, project = get_bigquery_client()

    if not client:
        st.error("Cannot connect to BigQuery. Please check your credentials.")
        return

    st.success(f"Connected to project: **{project}**")

    # Sidebar configuration
    st.sidebar.header("Configuration")

    # Auto-refresh settings
    auto_refresh = st.sidebar.checkbox("Auto-refresh", value=False)
    if auto_refresh:
        refresh_interval = st.sidebar.slider(
            "Refresh interval (seconds)",
            min_value=10,
            max_value=300,
            value=30
        )

    # Dataset selection
    datasets = get_datasets(project)

    if not datasets:
        st.warning("No datasets found in this project.")
        return

    selected_dataset = st.sidebar.selectbox(
        "Select Dataset",
        datasets,
        index=0
    )

    # Table selection
    tables = get_tables(project, selected_dataset)

    if not tables:
        st.warning(f"No tables found in dataset '{selected_dataset}'")
        return

    selected_table = st.sidebar.selectbox(
        "Select Table",
        tables,
        index=0
    )

    # Display timestamp
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Main content area
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Overview",
        "📋 Sample Data",
        "📊 Visualizations",
        "🔍 Detailed Data Characteristics"
    ])

    # Tab 1: Overview
    with tab1:
        st.header(f"Table: {selected_dataset}.{selected_table}")

        # Get table info
        table_info = get_table_info(project, selected_dataset, selected_table)

        if table_info:
            # Display KPIs
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric(
                    "Total Rows",
                    f"{table_info['num_rows']:,}"
                )

            with col2:
                size_mb = table_info['num_bytes'] / (1024 * 1024)
                st.metric(
                    "Size (MB)",
                    f"{size_mb:,.2f}"
                )

            with col3:
                st.metric(
                    "Columns",
                    table_info['schema_fields']
                )

            with col4:
                st.metric(
                    "Table Type",
                    table_info['table_type']
                )

            # Display timestamps
            st.markdown("---")
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"**Created:** {table_info['created'].strftime('%Y-%m-%d %H:%M:%S')}")

            with col2:
                st.markdown(f"**Last Modified:** {table_info['modified'].strftime('%Y-%m-%d %H:%M:%S')}")

                # Data freshness indicator
                time_since_modified = datetime.now(table_info['modified'].tzinfo) - table_info['modified']

                if time_since_modified < timedelta(hours=1):
                    st.success("🟢 Very fresh (< 1 hour)")
                elif time_since_modified < timedelta(days=1):
                    st.info("🟡 Fresh (< 1 day)")
                elif time_since_modified < timedelta(days=7):
                    st.warning("🟠 Moderate (< 1 week)")
                else:
                    st.error("🔴 Stale (> 1 week)")

    # Tab 2: Sample Data
    with tab2:
        st.header("Sample Data")

        sample_size = st.slider("Number of rows to display", 10, 1000, 100)

        df = query_table_sample(project, selected_dataset, selected_table, limit=sample_size)

        if df is not None and not df.empty:
            st.dataframe(df, use_container_width=True, height=400)

            # Download button
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name=f"{selected_dataset}_{selected_table}_sample.csv",
                mime="text/csv"
            )
        else:
            st.warning("No data available")

    # Tab 3: Visualizations
    with tab3:
        st.header("Data Visualizations")

        df = query_table_sample(project, selected_dataset, selected_table, limit=1000)

        if df is not None and not df.empty:
            # Time series visualization
            time_data = get_time_series_data(project, selected_dataset, selected_table)

            if time_data:
                time_df, time_column = time_data
                st.subheader(f"Time Series: Records per Day (by {time_column})")

                fig = px.line(
                    time_df,
                    x='date',
                    y='count',
                    title=f"Records over time",
                    labels={'date': 'Date', 'count': 'Record Count'}
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)

            # Column statistics
            st.subheader("Column Statistics")

            numeric_columns = df.select_dtypes(include=['number']).columns.tolist()

            if numeric_columns:
                selected_column = st.selectbox("Select numeric column", numeric_columns)

                col1, col2 = st.columns(2)

                with col1:
                    # Histogram
                    fig = px.histogram(
                        df,
                        x=selected_column,
                        title=f"Distribution of {selected_column}",
                        nbins=50
                    )
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    # Box plot
                    fig = px.box(
                        df,
                        y=selected_column,
                        title=f"Box Plot of {selected_column}"
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No numeric columns found for visualization")

            # Categorical columns
            categorical_columns = df.select_dtypes(include=['object', 'category']).columns.tolist()

            if categorical_columns:
                st.subheader("Categorical Analysis")
                selected_cat_column = st.selectbox("Select categorical column", categorical_columns)

                # Value counts
                value_counts = df[selected_cat_column].value_counts().head(10)

                fig = px.bar(
                    x=value_counts.index,
                    y=value_counts.values,
                    title=f"Top 10 values in {selected_cat_column}",
                    labels={'x': selected_cat_column, 'y': 'Count'}
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No data available for visualization")

    # Tab 4: Detailed Data Characteristics (ydata-profiling)
    with tab4:
        st.header("🔍 Detailed Data Characteristics")
        st.markdown("Comprehensive data profiling using ydata-profiling")

        # Option to generate profile
        if st.button("Generate Detailed Profile Report", type="primary"):
            df = query_table_sample(project, selected_dataset, selected_table, limit=10000)

            if df is not None and not df.empty:
                profile = generate_profiling_report(
                    df,
                    title=f"{selected_dataset}.{selected_table} - Data Profile"
                )

                if profile:
                    # Save to temp file and display
                    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as f:
                        profile.to_file(f.name)

                        # Read and display
                        with open(f.name, 'r', encoding='utf-8') as html_file:
                            html_content = html_file.read()
                            components.html(html_content, height=1000, scrolling=True)

                        # Download button
                        st.download_button(
                            label="Download Profile Report",
                            data=html_content,
                            file_name=f"{selected_dataset}_{selected_table}_profile.html",
                            mime="text/html"
                        )

                        # Clean up
                        os.unlink(f.name)
            else:
                st.warning("No data available for profiling")
        else:
            st.info("👆 Click the button above to generate a comprehensive data profile report")
            st.markdown("""
            The detailed profile report includes:
            - **Overview**: Dataset statistics, variable types, warnings
            - **Variables**: Detailed analysis of each column
            - **Interactions**: Correlation matrices and scatter plots
            - **Correlations**: Pearson, Spearman, Kendall correlations
            - **Missing Values**: Analysis of missing data patterns
            - **Sample**: First and last rows of the dataset

            *Note: For large tables, only the first 10,000 rows are profiled to ensure performance.*
            """)

    # Auto-refresh logic
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()

if __name__ == "__main__":
    main()
