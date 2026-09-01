# SQL Query Executor

A simple web interface to execute SQL queries against BigQuery datasets in your Workbench workspace.

## Features

- **SQL Text Editor**: Write and execute SELECT queries
- **Query Results**: View results in an interactive table
- **Query Statistics**: See bytes processed, slot time, and row count
- **CSV Export**: Download query results
- **Schema Viewer**: Inspect column types and sample values
- **Helper Queries**: Quick buttons to list datasets and tables

## Usage

### Basic Query
```sql
SELECT *
FROM `project.dataset.table`
LIMIT 100
```

### Fully Qualified Table Names
When querying datasets from other projects (shared datasets), use the full path:
```sql
SELECT *
FROM `source-project.dataset.table`
LIMIT 100
```

### List Your Datasets
```sql
SELECT schema_name as dataset
FROM `your-project.INFORMATION_SCHEMA.SCHEMATA`
ORDER BY schema_name
```

### Show Tables in a Dataset
```sql
SELECT
  table_schema as dataset,
  table_name,
  table_type,
  row_count
FROM `your-project.dataset.__TABLES__`
ORDER BY table_name
```

## Query Features Supported

- ✅ SELECT statements
- ✅ JOINs across tables
- ✅ Aggregations (COUNT, SUM, AVG, etc.)
- ✅ GROUP BY and ORDER BY
- ✅ WHERE clauses
- ✅ CTEs (WITH clauses)
- ✅ Subqueries
- ✅ Cross-project queries

## Technical Details

- **Framework**: Streamlit
- **Port**: 8501
- **Base Image**: python:3.11-slim
- **Dependencies**: streamlit, pandas, google-cloud-bigquery

## Authentication

Uses Google Cloud Application Default Credentials (ADC) automatically configured by Workbench.

## Tips

1. **Always use LIMIT** to avoid processing large datasets
2. **Use backticks** around table names: `` `project.dataset.table` ``
3. **Check bytes processed** before running expensive queries
4. **Download results** as CSV for further analysis
5. **Use the sidebar helpers** to explore your datasets
