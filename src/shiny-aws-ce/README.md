# shiny-aws-ce (AWS Cost Explorer Shiny Dashboard)

An R Shiny dashboard for analyzing AWS cost data using the Cost Explorer API. This template is designed to run on workbench and provides comprehensive cost analysis across compute, storage, and workspace resources.

## Features

- **Overview Dashboard**: Total cost summaries and trends across all AWS services
- **Compute Analysis**: Detailed EC2 instance type and family cost breakdown
- **Storage Analysis**: S3 and EBS cost visualization
- **EC2-Other Usage**: Analysis of non-instance EC2 costs
- **Workspaces**: EC2 workspace cost tracking
- **Omics Workspaces**: Specialized workspace cost analysis
- **Automatic CSV Synchronization**: Continuously monitors and copies CSV files from workspace to the app

## Prerequisites

- AWS Cost Explorer data exported to CSV files
- Docker and Docker Compose
- Access to AWS CLI (included in the devcontainer)

## Required Data Files

The application expects cost data in CSV format. Place your CSV files in `/root/workspace` (or any subdirectory), and they will be automatically copied to the Shiny app directory.

### Core Cost Data
- `cost_by_category.csv` - Cost aggregated by category
- `daily_cost_trends.csv` - Daily cost trends across categories
- `cost_by_region.csv` - Regional cost breakdown
- `top_services.csv` - Top AWS services by cost
- `service_usage_lines.csv` - Detailed service usage

### Compute Data
- `ec2_instance_types.csv` - EC2 instance type costs
- `ec2_families.csv` - EC2 instance family costs
- `ec2_cost_by_region.csv` - EC2 costs by region
- `ec2_instance_daily.csv` - Daily EC2 instance costs (optional, for date filtering)

### Storage Data
- `s3_buckets.csv` - S3 bucket costs
- `ebs_by_region.csv` - EBS costs by region
- `s3_daily_costs.csv` - Daily S3 costs (optional)
- `ebs_daily_costs.csv` - Daily EBS costs (optional)

### EC2-Other Data
- `ec2_other_categories.csv` - EC2-Other cost categories
- `ec2_other_usage_lines.csv` - Detailed EC2-Other usage
- `ec2_other_usage_summary.csv` - EC2-Other summary

### Workspace Data
- `workspaces_ec2.csv` - EC2 workspace costs
- `workspaces_omics.csv` - Omics workspace costs (optional)
- `workspaces_ec2_daily.csv` - Daily EC2 workspace costs (optional)
- `workspaces_omics_daily.csv` - Daily Omics workspace costs (optional)

## Setup Instructions

1. **Build and start the container**:
   ```bash
   docker-compose up -d --build
   ```

2. **Access the dashboard**:
   Navigate to `http://localhost:3838` in your web browser

3. **Upload your CSV files**:
   Place your AWS Cost Explorer CSV files in `/root/workspace` (or any subdirectory). The automatic CSV synchronization script will:
   - Scan for CSV files every 5 seconds
   - Copy new or updated files to `/srv/shiny-server/verily_cost/`
   - Skip files that already exist with the same size

## Automatic CSV Synchronization

The devcontainer includes an automatic CSV file synchronization script (`/workspace/scripts/copy-csv-files.sh`) that:

- Runs automatically on container start via `postStartCommand`
- Monitors `/root/workspace` for CSV files
- Copies files to `/srv/shiny-server/verily_cost/` where the Shiny app can access them
- Only copies files that are new or have changed (based on file size)
- Logs output to `/root/.workbench/logs/copy-csv-files.log`

To check the synchronization logs:
```bash
tail -f /root/.workbench/logs/copy-csv-files.log
```

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | aws |
| login | Whether to log in to workbench CLI | string | false |

## Dashboard Features

### Global Date Filtering
All visualizations respect the global date range filter, allowing you to analyze costs for:
- Last 30 days
- Last 60 days
- Last 90 days
- Custom date range

### Interactive Visualizations
- Time series plots with daily/monthly granularity
- Cost breakdown pie charts
- Regional cost distribution
- Instance type and family analysis
- Interactive data tables with CSV export

## Troubleshooting

### Application doesn't start
- Check that all required CSV files are present in `/root/workspace` or have been copied to `/srv/shiny-server/verily_cost/`
- View container logs: `docker logs application-server`
- Check CSV sync logs: `tail -f /root/.workbench/logs/copy-csv-files.log`

### Data not loading
- Ensure CSV files have the correct column names
- Verify files are being copied by checking the sync logs
- Check file permissions in the `/srv/shiny-server/verily_cost/` directory
- Look for error messages in the Shiny app logs

### CSV files not syncing
- Check if the copy script is running: `ps aux | grep copy-csv-files.sh`
- Review the sync logs: `tail -f /root/.workbench/logs/copy-csv-files.log`
- Manually restart the script:
  ```bash
  nohup /workspace/scripts/copy-csv-files.sh > /root/.workbench/logs/copy-csv-files.log 2>&1 &
  ```

### Port already in use
If port 3838 is already in use, modify the `docker-compose.yaml` file:
```yaml
ports:
  - "8080:3838"  # Change 8080 to any available port
```

## Development

To modify the dashboard:

1. Edit `app.R` to customize visualizations or add new features
2. Rebuild the container: `docker-compose up -d --build`
3. Refresh your browser to see changes

To modify the CSV synchronization script:

1. Edit `/workspace/scripts/copy-csv-files.sh`
2. Restart the script or restart the container

## File Structure

```
shiny-aws-ce/
├── .devcontainer.json          # Devcontainer configuration
├── devcontainer-template.json  # Template metadata
├── docker-compose.yaml         # Docker Compose configuration
├── Dockerfile                  # Container build instructions
├── shiny-customized.conf       # Shiny Server configuration
├── app.R                       # Main Shiny application
├── scripts/
│   └── copy-csv-files.sh      # CSV synchronization script
└── README.md                  # This file
```

## License

See the [LICENSE](https://github.com/verily-src/workbench-app-devcontainers/blob/master/LICENSE) file for details.

---

_Note: This file was auto-generated from the [devcontainer-template.json](https://github.com/verily-src/workbench-app-devcontainers/blob/main/src/shiny-aws-ce/devcontainer-template.json)._
