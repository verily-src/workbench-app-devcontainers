# scExploreR - Single Cell Data Explorer

An interactive Shiny application for exploring single-cell omics data without coding expertise.

## What is scExploreR?

scExploreR is a web-based visualization tool that allows researchers to explore single-cell RNA-seq and other omics datasets through an intuitive interface. It supports multiple data formats including:
- Seurat objects (.rds)
- SingleCellExperiment objects (.rds)
- Anndata objects (.h5ad)

## Features

- **No-code interface**: Biologists can explore complex datasets without programming
- **Multi-dataset browser**: Users can select from multiple datasets at runtime
- **Interactive visualizations**: UMAP/tSNE plots, gene expression, differential expression, and more
- **GCS integration**: Load data directly from mounted workspace buckets
- **Runtime dataset switching**: Click "Choose Dataset" in the app to switch between configured datasets

## Quick Start

### 1. Prepare Your Data

Store your pre-processed single-cell objects in your workspace GCS bucket. Supported formats:
- Seurat objects (.rds)
- SingleCellExperiment objects (.rds)
- Anndata objects (.h5ad)

Your data must be **pre-processed** (normalized, clustered, with UMAP/tSNE computed).

### 2. Launch the App

Create an app instance using this template in Workbench. The Docker image includes:
- scExploreR pre-installed and ready to use
- All required R packages and dependencies
- Config template that will be copied to `/workspace/config.yaml` on first run

The app will start automatically and be accessible through the Workbench interface.

### 3. Configure Your Datasets

Your workspace buckets are mounted at `/home/rstudio/workspace/<bucket-name>/`

#### Option A: Quick Start (Edit config.yaml directly)

If you already have config files for your datasets:

1. Edit `/workspace/config.yaml`:
```yaml
datasets:
    my_dataset:
        object: /home/rstudio/workspace/my-bucket/data/seurat_object.rds
        config: /home/rstudio/workspace/my-bucket/data/seurat_config.yaml
```

2. Restart the app container

#### Option B: Create Dataset Configs (Recommended)

For each dataset, you need to create a configuration file using scExploreR's config app:

1. Open RStudio in the app (if available) or use R console
2. Run the config app:
```r
scExploreR::run_config_app(
    object_path = "/home/rstudio/workspace/my-bucket/data/seurat_object.rds"
)
```
3. Fill in dataset information:
   - Dataset label (display name)
   - Dataset description
   - Preview image or plot
   - Metadata groupings
   - Assay selections
4. Save the config file to your workspace bucket
5. Update `/workspace/config.yaml` to reference this dataset and config
6. Restart the app

### 4. Access the App

Once configured, access the app through the Workbench interface. Users can:
- Click the ellipsis menu (...) in the top right
- Select "Choose Dataset" to switch between configured datasets
- Explore data through interactive visualizations

## Configuration Details

### Browser Config File Structure

The main config file (`/workspace/config.yaml`) lists all available datasets:

```yaml
datasets:
    dataset_1:
        object: /home/rstudio/workspace/bucket/path/to/object1.rds
        config: /home/rstudio/workspace/bucket/path/to/config1.yaml

    dataset_2:
        object: /home/rstudio/workspace/bucket/path/to/object2.rds
        config: /home/rstudio/workspace/bucket/path/to/config2.yaml

deployment_name: "My scExploreR Instance"

admin:
    name: "Your Name"
    email: "your.email@example.com"
```

### Dataset Config Files

Each dataset needs its own config file (created via `run_config_app`) that specifies:
- Dataset label and description
- Metadata columns to display
- Which assays to use (RNA, ADT, etc.)
- Color schemes
- Preview visualizations

See the [scExploreR Config Documentation](https://amc-heme.github.io/scExploreR/articles/config_documentation.html) for details.

## Workflow Summary

```
1. Process single-cell data → 2. Upload to GCS bucket → 3. Launch app
                                                              ↓
                               5. Access app in browser ← 4. Configure datasets
                                         ↓
                               6. Click "Choose Dataset" to explore
```

## Supported Data Formats

### Seurat Objects
- Standard Seurat v3, v4, or v5 objects
- Supports BPCells assays (for memory-efficient large datasets)
- Must have dimensionality reduction computed (UMAP/tSNE)

### SingleCellExperiment
- Standard Bioconductor SingleCellExperiment objects
- Supports HDF5-backed storage for large datasets
- Must have reduced dimensions in `reducedDims` slot

### Anndata
- Python scanpy-compatible .h5ad files
- Requires reticulate with Python packages: numpy, pandas, scipy, anndata, scanpy
- Must have UMAP/tSNE in `.obsm` slot

## Troubleshooting

### App won't start
- Check that `/workspace/config.yaml` exists and has valid paths
- Verify your object files exist at the specified paths
- Check container logs for installation errors

### Dataset not loading
- Ensure the object path is correct and accessible
- Verify the object is a valid Seurat/SCE/Anndata object
- Check that the config file path is correct

### Can't see my GCS bucket
- Verify the bucket is mounted at `/home/rstudio/workspace/`
- Check Workbench resource mounting settings
- Ensure the app has permission to access the bucket

## Port

The app runs on port 3838 (Shiny Server default).

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

## Resources

- [scExploreR GitHub](https://github.com/amc-heme/scExploreR)
- [scExploreR Documentation](https://amc-heme.github.io/scExploreR/)
- [Dataset Setup Walkthrough](https://amc-heme.github.io/scExploreR/articles/dataset_setup_walkthrough.html)
- [Configuration Guide](https://amc-heme.github.io/scExploreR/articles/config_documentation.html)

## Advanced Usage

### Running the Config App

To create or edit dataset configurations:

```r
# In R console or RStudio
scExploreR::run_config_app(
    object_path = "/path/to/your/object.rds",
    config_path = "/path/to/existing/config.yaml"  # optional
)
```

### Single Dataset Mode

For a single dataset without the browser config:

```r
scExploreR::run_scExploreR(
    object_path = "/path/to/object.rds",
    config_path = "/path/to/config.yaml",
    host = "0.0.0.0",
    port = 3838
)
```

---

_Note: This file was auto-generated from the [devcontainer-template.json](https://github.com/verily-src/workbench-app-devcontainers/blob/main/src/scexplorer/devcontainer-template.json). Add additional notes to a `NOTES.md`._
