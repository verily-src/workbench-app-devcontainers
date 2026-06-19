# Streamlit Dashboard Template

An interactive data dashboard template for Verily Workbench with GCS and BigQuery integration.

## Features

- **GCS File Browser**: Browse and preview files from workspace buckets
- **BigQuery Explorer**: Run SQL queries and view results
- **Data Visualization**: Create charts from uploaded CSV or query results
- **Workspace Resources**: Auto-discovery of workspace buckets and datasets

## Tabs

| Tab | Description |
|-----|-------------|
| GCS Files | Browse bucket contents, preview CSV files |
| BigQuery | Run SQL queries, view results in tables |
| Visualize | Create line, bar, or scatter charts |

## Customization

1. Edit `app/main.py` to add new visualizations
2. Update `app/requirements.txt` for additional libraries
3. Add new tabs for custom functionality

## Local Testing

```bash
cd app && pip install -r requirements.txt && streamlit run main.py
```

## Workspace Resources

Access workspace resources via environment variables:
- `WORKBENCH_<resource_name>` contains the resource path
- Resources are auto-displayed in the sidebar

## Example Usage

1. Select a bucket from the sidebar
2. Browse files and preview CSVs
3. Run BigQuery queries in the BigQuery tab
4. Visualize data in the Visualize tab
