# RS Single-Cell Toolkit (rs-sc-toolkit)

A comprehensive VSCode-based development environment for single-cell RNA sequencing analysis, combining R, Python, and workflow management tools.

## Features

This devcontainer provides a complete toolkit for single-cell analysis including:

### R Environment
- **R Base**: Latest R interpreter
- **Seurat**: Comprehensive R package for single-cell genomics
- **Bioconductor Packages**:
  - SingleCellExperiment, scater, scran
  - DropletUtils, edgeR, limma, DESeq2
  - ComplexHeatmap, dittoSeq
  - celldex, SingleR
- **Tidyverse**: Complete suite of data science packages
- **Visualization**: ggplot2, pheatmap, patchwork, cowplot, viridis

### Python Environment (SCVERSE Ecosystem)
- **scanpy**: Single-cell analysis in Python
- **anndata**: Annotated data structures
- **scvi-tools**: Deep generative models for single-cell analysis
- **muon**: Multimodal omics analysis
- **squidpy**: Spatial molecular data analysis
- **cellrank**: Lineage and cell fate prediction
- **scvelo**: RNA velocity analysis

### Workflow Management
- **Nextflow**: Data-driven computational pipelines
- **Snakemake**: Python-based workflow management system

### IDE
- **VS Code Server**: Full-featured code editor accessible via browser
- Support for R, Python, Jupyter notebooks, and data files

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

## File Support

This environment can open and work with:
- R scripts (.R, .Rmd)
- Python scripts (.py)
- Jupyter notebooks (.ipynb)
- Single-cell data files (.h5ad, .h5)
- Standard data formats (.csv, .tsv, .json, .xml)
- Source code (.c, .cpp, .java, .js, .ts, .sh)
- Documentation (.md, .html)

## Usage

This template is designed for:
- Single-cell RNA-seq analysis workflows
- Multi-omics data integration
- Spatial transcriptomics analysis
- Developing reproducible analysis pipelines
- Interactive data exploration and visualization

## Getting Started

After launching the environment:

1. **R**: Use the integrated terminal to run R scripts or start an R session with `R`
2. **Python**: Run Python scripts or start a Python REPL with `python3`
3. **Jupyter**: Install additional Jupyter support if needed
4. **Nextflow**: Create and run Nextflow pipelines with `nextflow run`
5. **Snakemake**: Execute Snakemake workflows with `snakemake`

## Installed System Dependencies

The environment includes all necessary system libraries for:
- HDF5 file handling
- Spatial data processing (GDAL, GEOS, PROJ)
- Image processing
- Scientific computing

---

_Note: This template provides a comprehensive environment for single-cell analysis. Building the container may take several minutes due to the installation of R and Python packages._
