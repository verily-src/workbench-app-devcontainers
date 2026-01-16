
# R Shiny Dashboard (r-shiny-app)

A Template to run R Shiny Dashboard applications on Workbench

## Description

This devcontainer provides a complete environment for running RShiny applications, specifically configured for the AWS Cost Analysis Dashboard. The container includes:

- **Shiny Server** running on port 3838
- All required R packages for the dashboard (shiny, shinydashboard, DT, plotly, dplyr, ggplot2, lubridate, scales, readr, shinycssloaders, tidyr, stringr)
- AWS CLI and Google Cloud CLI for cloud integration
- Workbench tools for data management

## Features

- **Base Image**: Rocker tidyverse 4.5 with comprehensive R package ecosystem
- **Automatic Package Installation**: All required R packages are pre-installed
- **Cloud Integration**: AWS CLI and Google Cloud CLI pre-configured
- **Data Persistence**: Mounted volumes for data and workspace persistence
- **Security**: Configurable authentication and security options
- **Automatic CSV Detection**: Background scanner monitors workspace mount for CSV files and automatically copies them to the required directory

## Prerequisites

Before using this devcontainer, ensure you have:

1. Your RShiny application code in the `app/` directory
2. Required data files in the appropriate directory structure (e.g., `verily_cost/` for the AWS Cost Analysis Dashboard)
3. Proper network configuration for port 3838

## Data Requirements

The AWS Cost Analysis Dashboard requires CSV files in a `verily_cost/` directory with the following structure:

### Required Files:
- `cost_by_category.csv`
- `daily_cost_trends.csv`
- `cost_by_region.csv`
- `top_services.csv`
- `service_usage_lines.csv`
- `ec2_instance_types.csv`
- `ec2_families.csv`
- `ec2_cost_by_region.csv`
- `s3_buckets.csv`
- `ebs_by_region.csv`
- `ec2_other_categories.csv`
- `ec2_other_usage_lines.csv`
- `ec2_other_usage_summary.csv`
- `workspaces_ec2.csv`

### Optional Files:
- `ec2_instance_daily.csv` (for daily EC2 instance cost trends)
- `workspaces_omics.csv` (for Omics workspace data)
- `s3_daily_costs.csv` (for S3 daily cost breakdown)
- `ebs_daily_costs.csv` (for EBS daily cost breakdown)
- `workspaces_ec2_daily.csv` (for workspace daily costs)
- `workspaces_omics_daily.csv` (for Omics workspace daily costs)

## Usage

### Option 1: Direct Data Placement
1. Place your data files in the `verily_cost/` directory
2. Launch the devcontainer
3. The Shiny Server will automatically start and serve your application
4. Access the dashboard at `http://localhost:3838`

### Option 2: Automatic CSV Discovery (Recommended)
1. Place your CSV files in the workspace mount directory (`/root/workspace`)
2. Launch the devcontainer
3. The CSV scanner will automatically detect and copy CSV files to `/srv/shiny-server/verily_cost/`
4. The scanner runs continuously in the background, monitoring for new CSV files every 5 seconds
5. Access the dashboard at `http://localhost:3838`

The CSV scanner logs its activity to `/root/.workbench/logs/csv_scanner.log` for debugging purposes.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

## Application Features

The AWS Cost Analysis Dashboard provides:

### Overview Tab
- Total cost summary with breakdown by compute and storage
- Cost trends over time (daily/monthly views)
- Cost distribution by category
- Top services by cost

### Compute Analysis Tab
- EC2 instance cost analysis by family and type
- Regional cost distribution
- Daily cost trends
- Detailed instance usage tables

### Storage Analysis Tab
- S3 bucket cost distribution
- EBS cost by region
- Daily cost breakdowns
- Storage trends over time

### EC2-Other Usage Tab
- Cost breakdown by category
- Top usage types
- Detailed usage information

### Workspaces Tab
- Workspace cost distribution
- Cost vs hours analysis
- Detailed workspace metrics

### Omics Workspaces Tab
- Omics workspace cost analysis
- Usage patterns and trends

## Configuration

The devcontainer is configured with:

- **Port**: 3838 (Shiny Server default)
- **Working Directory**: `/workspace`
- **User Home**: `/home/shiny`
- **Authentication**: Disabled by default (set `DISABLE_AUTH` environment variable)
- **CSV Scanner**: Automatically runs on container start via `postStartCommand`

### CSV Scanner Details

The CSV scanner (`/workspace/scripts/csv_scanner.sh`) performs the following:

1. **Continuous Monitoring**: Scans `/root/workspace` every 5 seconds for CSV files
2. **Smart Copying**: Only copies files that are new or have changed (based on file size)
3. **Automatic Directory Creation**: Creates the destination directory if it doesn't exist
4. **Logging**: All activity is logged to `/root/.workbench/logs/csv_scanner.log`

The scanner script is similar in design to the cirrocumulus scanner pattern, adapted specifically for CSV file management.

## Customization

To customize the dashboard:

1. Modify `app/app.R` with your application code
2. Update R package requirements in `.devcontainer.json`
3. Adjust Shiny Server configuration in `docker-compose.yaml`

## Troubleshooting

### Application doesn't start
- Check that all required data files are present
- Verify that the `verily_cost/` directory is accessible
- Check Shiny Server logs for errors

### Data not loading
- Ensure CSV files are properly formatted
- Verify file permissions
- Check that date columns are in the correct format (YYYY-MM-DD)
- Check the CSV scanner log at `/root/.workbench/logs/csv_scanner.log` to see if files are being detected and copied
- Verify CSV files are in `/root/workspace` directory

### CSV Scanner not working
- Check if the scanner process is running: `ps aux | grep csv_scanner`
- Review the scanner log: `tail -f /root/.workbench/logs/csv_scanner.log`
- Ensure CSV files have `.csv` extension (case-sensitive)
- Verify the scanner script has execute permissions: `ls -l /workspace/scripts/csv_scanner.sh`
- Manually run the scanner: `/workspace/scripts/csv_scanner.sh` (stop with Ctrl+C)

### Port conflicts
- Ensure port 3838 is not already in use
- Update the port mapping in `docker-compose.yaml` if needed

## Support

For issues and questions:
- Check the GitHub repository for updates
- Review Shiny Server documentation at https://shiny.rstudio.com/
- Consult Rocker documentation at https://rocker-project.org/

---

_Note: This file was auto-generated from the [devcontainer-template.json](https://github.com/verily-src/workbench-app-devcontainers/blob/main/src/r-shiny-app/devcontainer-template.json). Add additional notes to a `NOTES.md`._
