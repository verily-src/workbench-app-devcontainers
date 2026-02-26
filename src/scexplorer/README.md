# scExploreR - Single Cell Data Explorer

This devcontainer provides a complete environment for running [scExploreR](https://github.com/amc-heme/scExploreR), a Shiny application for single-cell omics data visualization and analysis.

## Overview

scExploreR (v1.0.0) is a comprehensive Shiny application designed for interactive exploration of single-cell RNA-seq data. It supports multiple data formats including Seurat, SingleCellExperiment, and Anndata objects.

## Features

- Interactive visualization of single-cell data
- Support for multiple data formats (Seurat, SingleCellExperiment, Anndata)
- Dimensionality reduction plots (UMAP, t-SNE)
- Feature expression visualization
- Differential expression analysis
- Multi-dataset browser mode
- User-friendly interface for non-bioinformaticians

## Prerequisites

- Docker and Docker Compose installed
- A pre-processed single cell data object in one of the supported formats:
  - Seurat object (.rds)
  - SingleCellExperiment object (.rds)
  - Anndata object (.h5ad)

## Getting Started

### 1. Prepare Your Data

scExploreR requires a pre-processed single cell data object. Place your data file at:

```
/srv/shiny-server/scexplorer/data/object.rds
```

For the container, mount your data directory or copy files to the appropriate location.

### 2. Configuration (Optional)

For advanced features, you can configure your object using the scExploreR configuration app:

```R
scExploreR::run_config(
  object_path = "/path/to/your/object.rds",
  config_path = "/path/to/save/config.yaml"
)
```

Save the generated configuration file as:

```
/srv/shiny-server/scexplorer/data/object_config.yaml
```

### 3. Multi-Dataset Mode (Optional)

To serve multiple datasets, create a browser configuration file at:

```
/srv/shiny-server/scexplorer/data/config.yaml
```

Example browser config:

```yaml
datasets:
  - name: "Dataset 1"
    object_path: "/srv/shiny-server/scexplorer/data/dataset1.rds"
    config_path: "/srv/shiny-server/scexplorer/data/dataset1_config.yaml"
  - name: "Dataset 2"
    object_path: "/srv/shiny-server/scexplorer/data/dataset2.rds"
    config_path: "/srv/shiny-server/scexplorer/data/dataset2_config.yaml"
```

## Data Formats

### Seurat Objects

Most common format for single-cell analysis in R. Ensure your Seurat object:
- Has been normalized
- Contains dimensionality reduction (UMAP/t-SNE)
- Has cell metadata
- Has been clustered

### Anndata Objects

For Python-based workflows. Requirements:
- Processed using scanpy or similar tools
- Contains embeddings (X_umap, X_tsne)
- Has observations (cell metadata)
- Has variable features

The container includes Python support with numpy, pandas, scipy, anndata, and scanpy pre-installed.

## File Structure

```
src/scexplorer/
├── .devcontainer.json           # VS Code devcontainer configuration
├── devcontainer-template.json   # Template metadata
├── Dockerfile                   # Container build instructions
├── docker-compose.yaml          # Service orchestration
├── app.R                        # Application launcher script
├── shiny-customized.conf        # Shiny Server configuration
├── README.md                    # This file
└── data/                        # Place your data files here
    ├── object.rds               # Your single cell object
    ├── object_config.yaml       # Optional: object configuration
    └── config.yaml              # Optional: browser configuration
```

## Installed R Packages

### Core Shiny Packages
- shiny (≥1.6.1)
- shinydashboard (≥0.7.2)
- shinyWidgets (≥0.6.2)
- shinyBS (≥0.61.1)
- shinyjs (≥2.0.0)
- rintrojs (≥0.3.0)
- waiter (≥0.2.5)

### Data Analysis
- Seurat (≥3.0.0)
- dplyr
- tibble
- presto (from GitHub)
- SCUBA (from GitHub)
- scDE (from GitHub)

### Visualization
- ggplot2
- ggsci
- cowplot
- patchwork
- RColorBrewer
- viridisLite

### Bioconductor Packages
- HDF5Array
- SingleCellExperiment

### Python Support
- NumPy
- Pandas
- SciPy
- Anndata
- Scanpy

## Configuration Options

### Shiny Server Settings

The container is configured with:
- Port: 3838
- App initialization timeout: 60 seconds (for large datasets)
- App idle timeout: 3600 seconds (1 hour)

These can be adjusted in `shiny-customized.conf` if needed for very large datasets.

### Cloud Provider Integration

The devcontainer supports integration with cloud storage:
- AWS (with AWS CLI)
- GCP (with Google Cloud CLI)
- Azure

Configure cloud access through the devcontainer options:
- `cloud`: Select your cloud provider (gcp, aws, azure)
- `login`: Enable cloud authentication

## Troubleshooting

### Large Dataset Loading Issues

If you experience timeouts with large datasets:

1. Increase the `app_init_timeout` in `shiny-customized.conf`
2. Ensure your data object is optimized (remove unnecessary data)
3. Consider splitting into multiple smaller datasets

### Memory Issues

For large datasets, you may need to increase Docker's memory allocation:

```bash
# In docker-compose.yaml, add under the app service:
mem_limit: 16g
```

### Python/Anndata Support

If you encounter issues with Anndata objects:

1. Verify Python packages are installed:
   ```bash
   docker exec -it application-server pip3 list
   ```

2. Check reticulate configuration in R:
   ```R
   library(reticulate)
   py_config()
   ```

## Documentation and Support

- **scExploreR Documentation**: https://amc-heme.github.io/scExploreR/
- **GitHub Repository**: https://github.com/amc-heme/scExploreR
- **scExploreR Issues**: https://github.com/amc-heme/scExploreR/issues

## Version Information

- **scExploreR Version**: v1.0.0
- **R Version**: 4.5.0
- **Base Image**: rocker/shiny:4.5.0
- **Shiny Server**: Latest (from base image)

## License

This devcontainer configuration is part of the workbench-app-devcontainers project.

scExploreR itself is licensed under the MIT License. See the [scExploreR LICENSE](https://github.com/amc-heme/scExploreR/blob/main/LICENSE) for details.

## Citation

If you use scExploreR in your research, please cite the original authors. Visit the [scExploreR GitHub repository](https://github.com/amc-heme/scExploreR) for citation information.
