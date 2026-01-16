# Lab Results Analyzer (Development Version)

A JupyterLab-based Workbench application for analyzing lab results data and generating distribution reports.

**This is a development copy for iterative feature development.**

## Features

This app includes a sample Jupyter notebook (`Lab_Results_Analysis.ipynb`) that:
- Creates a sample dataset with lab results (Patient ID, Lab Type, Lab Value, Lab Date)
- Generates comprehensive distribution reports for each field:
  - **Patient ID**: Distribution of tests per patient with visualizations
  - **Lab Type**: Frequency analysis with bar charts and pie charts
  - **Lab Value**: Statistical analysis with histograms, box plots, and density plots
  - **Lab Date**: Temporal analysis with timeline plots and monthly/weekly distributions
- Provides summary statistics for all fields

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
