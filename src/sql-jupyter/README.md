# SQL Query Tool (Based on Working Example)

This app is based on the **proven working `example` app structure** but modified to run a SQL query interface.

## Why This Should Work

- ✅ Uses the **exact same devcontainer structure** as the working example app
- ✅ Same port (8888)
- ✅ Same network configuration
- ✅ Same startup scripts
- ✅ Only difference: runs SQL query interface instead of Jupyter

## Features

- Simple SQL text editor
- Execute SELECT queries against BigQuery
- View results in interactive table
- Download results as CSV
- Query statistics (bytes processed, rows returned)

## Usage

1. Open the app after deployment
2. Write your SQL query:
   ```sql
   SELECT * FROM \`project.dataset.table\` LIMIT 100
   ```
3. Click "Execute Query"
4. View results and download if needed

## First-Time Startup

The first time you start this app, it will take **2-3 minutes** to install dependencies (streamlit, pandas, BigQuery client). Subsequent restarts will be faster.

## Authentication

Uses the same Google Cloud credentials as the example app - no configuration needed!
