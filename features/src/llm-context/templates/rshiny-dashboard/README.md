# RShiny Dashboard Template

An interactive R-based dashboard template for Verily Workbench with Shiny.

## Features

- **Data Explorer**: Upload and explore CSV files
- **Visualization**: Create interactive charts with plotly
- **Workspace Resources**: View connected buckets and datasets
- **R Statistical Analysis**: Full R environment for data analysis

## Tabs

| Tab | Description |
|-----|-------------|
| Overview | Dashboard summary with resource counts |
| Data Explorer | Upload CSV files, view data tables |
| Visualization | Create scatter, line, bar, histogram charts |
| Resources | View all workspace resources |

## R Packages Included

- `shiny` & `shinydashboard` - UI framework
- `DT` - Interactive data tables
- `plotly` & `ggplot2` - Visualization
- `dplyr` & `tidyr` - Data manipulation
- `bigrquery` - BigQuery integration
- `googleCloudStorageR` - GCS integration

## Customization

1. Edit `app/app.R` to add new features
2. Modify `Dockerfile` to add R packages
3. Update dashboard layout in the UI section

## Local Testing

```bash
R -e "shiny::runApp('app', port=3838)"
```

## Workspace Resources

Access workspace resources via environment variables:
- `WORKBENCH_<resource_name>` contains the resource path
- Use `Sys.getenv()` to access in R code

## BigQuery Access Example

```r
library(bigrquery)

# Run a query
query <- "SELECT * FROM `project.dataset.table` LIMIT 100"
result <- bq_project_query("your-project", query)
df <- bq_table_download(result)
```

## GCS Access Example

```r
library(googleCloudStorageR)

# Set bucket
gcs_global_bucket("your-bucket-name")

# List objects
objects <- gcs_list_objects()

# Download file
gcs_get_object("path/to/file.csv", saveToDisk = "local_file.csv")
```
