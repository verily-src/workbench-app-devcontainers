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

The application expects cost data in CSV format. Place your CSV files in any workspace controlled S3 Folder (or any subdirectory), and they will be automatically copied to the Shiny app directory.

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

