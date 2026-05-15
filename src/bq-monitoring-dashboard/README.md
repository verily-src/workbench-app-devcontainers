# BigQuery Monitoring Dashboard

A comprehensive real-time monitoring dashboard for BigQuery datasets with detailed data profiling capabilities.

## Features

### 📈 Overview Tab
- **Key Metrics**: Total rows, table size, column count, table type
- **Timestamps**: Creation and last modification dates
- **Data Freshness Indicators**: Visual alerts for data age
  - 🟢 Very fresh (< 1 hour)
  - 🟡 Fresh (< 1 day)
  - 🟠 Moderate (< 1 week)
  - 🔴 Stale (> 1 week)

### 📋 Sample Data Tab
- View sample data from selected tables
- Adjustable row count (10-1000 rows)
- Download sample data as CSV

### 📊 Visualizations Tab
- **Time Series Analysis**: Automatic detection of timestamp columns
- **Distribution Analysis**: Histograms for numeric columns
- **Box Plots**: Statistical distribution visualization
- **Categorical Analysis**: Top value frequency charts

### 🔍 Detailed Data Characteristics Tab
- Comprehensive data profiling using **ydata-profiling**
- Includes:
  - Dataset overview and statistics
  - Variable type detection and analysis
  - Correlation matrices (Pearson, Spearman, Kendall)
  - Missing value analysis
  - Interaction plots
  - Sample data preview
- Downloadable HTML reports

## Configuration

### Auto-refresh
- Enable auto-refresh in the sidebar
- Configurable interval (10-300 seconds)

### Dataset & Table Selection
- Dropdown selection for all available datasets
- Dropdown selection for tables within selected dataset

## Technical Details

- **Framework**: Streamlit
- **Port**: 8501
- **Base Image**: Python 3.11-slim
- **Key Dependencies**:
  - `streamlit`: Web UI framework
  - `google-cloud-bigquery`: BigQuery client
  - `plotly`: Interactive visualizations
  - `ydata-profiling`: Comprehensive data profiling
  - `pandas`: Data manipulation

## Usage in Workbench

1. Create a custom app in Workbench
2. Point to this repository
3. Select "BigQuery Monitoring Dashboard" template
4. Choose cloud provider (GCP recommended)
5. Launch the app
6. Access via Workbench UI

## Authentication

The app uses Google Cloud Application Default Credentials (ADC) automatically configured by Workbench. No manual authentication required.

## Performance Notes

- Table metadata is cached for 5 minutes
- Query results are cached for 1 minute
- Data profiling is limited to 10,000 rows for performance
- Auto-refresh can be adjusted based on data update frequency

## Requirements

- Workbench workspace with BigQuery access
- GCP project with enabled BigQuery API
- Sufficient IAM permissions to query BigQuery datasets
