# Clinical Data Dashboard - Workbench Custom App

Interactive Streamlit dashboard for clinical data analysis in Verily Workbench.

## Features

### 1. Bubble Heatmap
- Visual representation of clinical labels by category and frequency
- Bubble size represents participant count
- Color intensity shows prevalence frequency

### 2. Disease Leaderboard
- Ranked list of diseases by total participant months
- Interactive disease selection
- Shows participant count and average months per participant

### 3. Disease Deep-Dive
- Longitudinal blood pressure trends by medication group
- Line charts with standard deviation ribbons
- Doctor visit markers on timeline
- Reference lines for normal and hypertensive ranges

## Data Sources

- **Diagnoses:** `wb-spotless-eggplant-4340.analysis.DIAGNOSES`
- **Vital Signs:** `wb-spotless-eggplant-4340.crf.VS`

## Deployment in Workbench

### Prerequisites
1. Push this repository to GitHub
2. Ensure your Workbench workspace has access to the BigQuery datasets

### Create Custom App

1. In Workbench UI, navigate to **Apps**
2. Click **Create Custom App**
3. Configure:
   - **App Name:** Clinical Dashboard
   - **Repository URL:** Your GitHub repository URL
   - **Branch:** `main` (or `master`)
   - **Dev Container Path:** `.` (root directory)
   - **Machine Type:** n1-highmem-2 (recommended)
   - **Disk Size:** 50 GB

### Access Dashboard

After the app starts (takes 5-10 minutes for first build):

```
https://workbench.verily.com/app/[APP_UUID]/proxy/8501/
```

Get your APP_UUID:
```bash
wb app list --format=json | jq -r '.[] | select(.appConfigName == "Clinical Dashboard") | .id'
```

## Local Testing (Optional)

```bash
# Create required Docker network
docker network create app-network

# Build and run
docker compose build
docker compose up

# Access at http://localhost:8501
```

## Configuration

The dashboard automatically connects to BigQuery using Workbench's default authentication.

**Target Project:** `wb-spotless-eggplant-4340`
**Datasets:**
- `analysis` - Clinical diagnoses and derived metrics
- `crf` - Clinical report forms including vital signs

## Troubleshooting

### Dashboard shows no data
- Verify your workspace has access to the BigQuery datasets
- Check that the app is running in the correct workspace

### Slow loading
- First load caches data - subsequent loads are faster
- Consider limiting query results if dataset is very large

### Connection errors
- Ensure the app has the required BigQuery permissions
- Check Workbench workspace resource access

## Tech Stack

- **Frontend:** Streamlit 1.31.0
- **Visualization:** Plotly 5.18.0
- **Data:** pandas, numpy
- **Database:** Google Cloud BigQuery
- **Container:** Python 3.11-slim

## Support

For issues or questions:
- Workbench Support: support@workbench.verily.com
- Workbench Docs: https://support.workbench.verily.com
