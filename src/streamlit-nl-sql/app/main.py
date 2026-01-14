"""Main Streamlit application for Natural Language to SQL."""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import sys
import os

# Add app directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from config import load_config
from security import SQLValidator
from gemini_service import GeminiNLToSQL
from bigquery_service import BigQueryService
from utils import format_bytes

# Page configuration
st.set_page_config(
    page_title="Natural Language to SQL",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'query_history' not in st.session_state:
    st.session_state.query_history = []
if 'current_dataset' not in st.session_state:
    st.session_state.current_dataset = None
if 'config' not in st.session_state:
    try:
        st.session_state.config = load_config()
    except Exception as e:
        st.error(f"⚠️ Configuration error: {str(e)}")
        st.info(
            "Make sure you're running in a Workbench environment or "
            "set the GCP_PROJECT environment variable."
        )
        st.stop()

# Initialize services
@st.cache_resource
def get_services():
    """Initialize and cache service instances."""
    config = st.session_state.config
    return {
        'validator': SQLValidator(config),
        'gemini': GeminiNLToSQL(config),
        'bigquery': BigQueryService(config)
    }

try:
    services = get_services()
except Exception as e:
    st.error(f"⚠️ Failed to initialize services: {str(e)}")
    st.stop()

# Sidebar
with st.sidebar:
    st.title("⚙️ Configuration")

    # Project info
    st.info(f"📁 Project: `{st.session_state.config.project_id}`")

    st.divider()

    # Dataset selection
    st.subheader("Dataset")
    datasets = services['bigquery'].list_datasets()

    if datasets:
        default_index = 0
        if st.session_state.current_dataset in datasets:
            default_index = datasets.index(st.session_state.current_dataset)

        selected_dataset = st.selectbox(
            "Select BigQuery Dataset",
            datasets,
            index=default_index
        )
        st.session_state.current_dataset = selected_dataset

        # Show dataset schema
        if st.checkbox("Show Schema", help="Display tables and columns in the dataset"):
            with st.spinner("Loading schema..."):
                schema = services['bigquery'].get_dataset_schema(selected_dataset)
                if "error" in schema:
                    st.error(f"Error: {schema['error']}")
                else:
                    for table_name, columns in schema.items():
                        with st.expander(f"📊 {table_name} ({len(columns)} columns)"):
                            for col in columns:
                                st.text(f"• {col['name']} ({col['type']})")
    else:
        st.warning("No datasets found or no permissions")

    st.divider()

    # Settings
    st.subheader("Settings")
    show_sql = st.checkbox("Show generated SQL", value=True)
    show_explanation = st.checkbox("Show explanation", value=True)
    auto_execute = st.checkbox(
        "Auto-execute queries",
        value=False,
        help="Automatically run queries after generation"
    )

    st.divider()

    # Query History
    st.subheader("📜 Query History")
    if st.session_state.query_history:
        for i, item in enumerate(reversed(st.session_state.query_history[-10:])):
            with st.expander(
                f"{item['timestamp']} - {item['nl_query'][:25]}...",
                expanded=False
            ):
                st.code(item['sql'], language='sql')
                st.caption(f"Rows: {item.get('row_count', 'N/A')}")
    else:
        st.info("No queries yet")

# Main content
st.title("🔍 Natural Language to SQL Query Interface")
st.markdown(
    "Convert natural language questions into SQL queries and visualize results using AI"
)

# Natural language input
col1, col2 = st.columns([3, 1])

with col1:
    nl_query = st.text_area(
        "Enter your question in natural language:",
        placeholder="e.g., Show me the top 10 customers by total revenue in 2023",
        height=100,
        key="nl_input"
    )

with col2:
    st.markdown("### 💡 Examples")
    if st.button("📊 Top 10 records", use_container_width=True):
        st.session_state.nl_input = "Show me top 10 records from the first table"
        st.rerun()
    if st.button("📈 Count records", use_container_width=True):
        st.session_state.nl_input = "Count the total number of records"
        st.rerun()
    if st.button("🔍 Show columns", use_container_width=True):
        st.session_state.nl_input = "Show all column names and their types"
        st.rerun()

# Generate SQL button
generate_col1, generate_col2 = st.columns([1, 4])
with generate_col1:
    generate_clicked = st.button(
        "🚀 Generate SQL",
        type="primary",
        disabled=not nl_query or not nl_query.strip(),
        use_container_width=True
    )

if generate_clicked:
    with st.spinner("🤖 Generating SQL query using Gemini..."):
        # Get schema context
        schema_context = None
        if st.session_state.current_dataset:
            schema_context = services['bigquery'].get_dataset_schema(
                st.session_state.current_dataset
            )

        # Generate SQL using Gemini
        result = services['gemini'].generate_sql(
            nl_query,
            dataset_schema=schema_context,
            conversation_history=st.session_state.query_history[-3:]
        )

        if result.get('error'):
            st.error(f"❌ Generation error: {result['error']}")
        elif result['sql']:
            st.session_state.generated_sql = result['sql']
            st.session_state.explanation = result['explanation']
            st.session_state.confidence = result['confidence']
            st.session_state.current_nl_query = nl_query

# Display generated SQL and execute
if 'generated_sql' in st.session_state and st.session_state.generated_sql:
    st.divider()

    # Confidence indicator
    confidence = st.session_state.confidence
    conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}
    st.markdown(
        f"**Confidence:** {conf_emoji.get(confidence, '⚪')} {confidence.title()}"
    )

    # Show explanation
    if show_explanation and st.session_state.explanation:
        st.info(f"💡 **Explanation:** {st.session_state.explanation}")

    # Show SQL
    if show_sql:
        st.code(st.session_state.generated_sql, language='sql')

    # SQL validation
    is_valid, validation_msg = services['validator'].validate_query(
        st.session_state.generated_sql
    )

    if is_valid:
        st.success(f"✅ {validation_msg}")

        # Execute controls
        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            execute_btn = st.button("▶️ Execute Query", type="primary")
        with col2:
            if st.button("✏️ Edit SQL"):
                st.session_state.edit_mode = True

        # Edit mode
        if st.session_state.get('edit_mode', False):
            edited_sql = st.text_area(
                "Edit SQL:",
                value=st.session_state.generated_sql,
                height=200,
                key="sql_editor"
            )
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("💾 Save", use_container_width=True):
                    st.session_state.generated_sql = edited_sql
                    st.session_state.edit_mode = False
                    st.rerun()

        # Execute query
        if execute_btn or (auto_execute and 'last_executed' not in st.session_state):
            st.session_state.last_executed = st.session_state.generated_sql

            with st.spinner("⚡ Executing query on BigQuery..."):
                df, metadata = services['bigquery'].execute_query(
                    st.session_state.generated_sql
                )

                if metadata['success']:
                    # Save to history
                    st.session_state.query_history.append({
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'nl_query': st.session_state.current_nl_query,
                        'sql': st.session_state.generated_sql,
                        'row_count': metadata['row_count']
                    })

                    # Display results
                    st.success("✅ Query executed successfully!")

                    # Metrics
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Rows", f"{metadata['row_count']:,}")
                    col2.metric("Time", f"{metadata['execution_time_ms']:,}ms")
                    col3.metric(
                        "Bytes Processed",
                        format_bytes(metadata['bytes_processed'])
                    )
                    col4.metric(
                        "Cache",
                        "✅ Hit" if metadata.get('cache_hit') else "❌ Miss"
                    )

                    # Data display
                    st.divider()
                    st.subheader("📊 Results")

                    # Tabs for different views
                    tab1, tab2, tab3 = st.tabs(["📋 Table", "📈 Visualize", "📥 Export"])

                    with tab1:
                        st.dataframe(df, use_container_width=True, height=400)

                    with tab2:
                        if len(df) > 0:
                            # Auto-suggest visualizations
                            numeric_cols = df.select_dtypes(
                                include=['number']
                            ).columns.tolist()
                            categorical_cols = df.select_dtypes(
                                include=['object', 'category']
                            ).columns.tolist()
                            all_cols = df.columns.tolist()

                            if numeric_cols or categorical_cols:
                                viz_col1, viz_col2 = st.columns(2)

                                with viz_col1:
                                    viz_type = st.selectbox(
                                        "Chart Type",
                                        ["Bar Chart", "Line Chart", "Scatter Plot", "Pie Chart"]
                                    )

                                with viz_col2:
                                    if viz_type in ["Bar Chart", "Line Chart", "Scatter Plot"]:
                                        x_col = st.selectbox("X-axis", all_cols)

                                if viz_type == "Bar Chart" and numeric_cols:
                                    y_col = st.selectbox("Y-axis", numeric_cols)
                                    fig = px.bar(df, x=x_col, y=y_col)
                                    st.plotly_chart(fig, use_container_width=True)

                                elif viz_type == "Line Chart" and numeric_cols:
                                    y_col = st.selectbox("Y-axis", numeric_cols)
                                    fig = px.line(df, x=x_col, y=y_col)
                                    st.plotly_chart(fig, use_container_width=True)

                                elif viz_type == "Scatter Plot" and len(numeric_cols) >= 2:
                                    y_col = st.selectbox(
                                        "Y-axis",
                                        [c for c in numeric_cols if c != x_col]
                                    )
                                    fig = px.scatter(df, x=x_col, y=y_col)
                                    st.plotly_chart(fig, use_container_width=True)

                                elif viz_type == "Pie Chart":
                                    if numeric_cols:
                                        values_col = st.selectbox("Values", numeric_cols)
                                        names_col = st.selectbox(
                                            "Labels",
                                            categorical_cols if categorical_cols else all_cols
                                        )
                                        fig = px.pie(df, names=names_col, values=values_col)
                                        st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("No suitable columns for visualization")
                        else:
                            st.info("No data to visualize")

                    with tab3:
                        st.markdown("### Download Results")
                        col1, col2 = st.columns(2)

                        with col1:
                            csv = df.to_csv(index=False)
                            st.download_button(
                                label="📥 Download as CSV",
                                data=csv,
                                file_name="query_results.csv",
                                mime="text/csv",
                                use_container_width=True
                            )

                        with col2:
                            json_data = df.to_json(orient='records', indent=2)
                            st.download_button(
                                label="📥 Download as JSON",
                                data=json_data,
                                file_name="query_results.json",
                                mime="application/json",
                                use_container_width=True
                            )

                else:
                    st.error(f"❌ Query failed: {metadata['error']}")
                    st.info(
                        "💡 **Tip:** Try rephrasing your question or checking the SQL syntax."
                    )

    else:
        st.error(f"❌ Security validation failed: {validation_msg}")
        st.warning(
            "The generated query contains potentially unsafe operations. "
            "Only SELECT queries are allowed."
        )

# Footer
st.divider()
st.markdown(
    """
    <div style='text-align: center; color: gray; font-size: 0.8em;'>
        🔒 This app only allows SELECT queries for security |
        Powered by Vertex AI Gemini and BigQuery
    </div>
    """,
    unsafe_allow_html=True
)
