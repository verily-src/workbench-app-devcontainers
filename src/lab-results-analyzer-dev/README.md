# Lab Results Analyzer (Development Version)

A JupyterLab-based Workbench application for analyzing lab results data and generating distribution reports.

**This is a development copy for iterative feature development.**

## Features

This app includes a Jupyter notebook (`Lab_Results_Analysis.ipynb`) that:
- **Reads data from Workbench data collections** (GCS buckets) or mounted workspace paths
- Supports multiple file formats: CSV, Parquet, JSON, Excel
- Generates comprehensive distribution reports for each field:
  - **Patient ID**: Distribution of tests per patient with visualizations
  - **Lab Type**: Frequency analysis with bar charts and pie charts
  - **Lab Value**: Statistical analysis with histograms, box plots, and density plots
  - **Lab Date**: Temporal analysis with timeline plots and monthly/weekly distributions
- Provides summary statistics for all fields
- Falls back to sample data generation if no data source is configured

## Data Source Configuration

The notebook can read data from:

1. **GCS Bucket** (Recommended): Direct access to Google Cloud Storage buckets
   - Set `GCS_BUCKET` and `FILE_NAME` in the notebook
   - Example: `GCS_BUCKET = "my-bucket"`, `FILE_NAME = "data/lab_results.csv"`

2. **Mounted Workspace Path**: Access data from mounted workspace resources
   - Set `USE_MOUNTED_PATH = True` and `MOUNTED_FILE_PATH`
   - Example: `MOUNTED_FILE_PATH = "/home/jovyan/workspaces/my-workspace/data/lab_results.csv"`

3. **Sample Data**: If no configuration is provided, generates sample data for testing

### Required Data Columns

Your data file should have these columns (case-insensitive):
- `Patient ID` (or `patient_id`, `PatientID`, etc.)
- `Lab Type` (or `lab_type`, `LabType`, etc.)
- `Lab Value` (or `lab_value`, `LabValue`, etc.)
- `Lab Date` (or `lab_date`, `LabDate`, etc.) - should be in a date format

## Configuration

- **Image**: jupyter/scipy-notebook (includes pandas, numpy, matplotlib, seaborn)
- **Port**: 8888
- **User**: jovyan
- **Home Directory**: /home/jovyan

## Access

Once deployed in Workbench:
1. Access JupyterLab at the app URL (port 8888)
2. Open the `Lab_Results_Analysis.ipynb` notebook
3. Run all cells to see the distribution reports

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:8888`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize ttyd options)
- `devcontainer-template.json` - Template options and metadata

## Testing

To test this app template:

```bash
cd test
./test.sh lab-results-analyzer-dev
```

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (lab-results-analyzer-dev)

## Development

This is a development version of the lab-results-analyzer app. Use this copy to:
- Iteratively add new features
- Test experimental changes
- Develop enhancements without affecting the original app
