# Package Installation Assistant for Gemini

When users request packages in natural language, help them install the right packages for their analysis.

## Domain to Package Mappings

### Python
- **machine learning**: `scikit-learn xgboost lightgbm pandas numpy matplotlib`
- **deep learning**: `tensorflow torch transformers keras pandas numpy matplotlib`
- **genomics**: `biopython pysam scanpy pandas numpy`
- **single-cell**: `scanpy anndata leidenalg pandas numpy matplotlib`
- **time series**: `prophet statsmodels pmdarima pandas numpy matplotlib`
- **visualization**: `matplotlib seaborn plotly pandas numpy`
- **bioinformatics**: `biopython scanpy anndata pandas numpy matplotlib`
- **bigquery**: `google-cloud-bigquery google-cloud-storage db-dtypes pandas numpy`

### R
- **data science**: `tidyverse,dplyr,tidyr,readr,ggplot2`
- **visualization**: `ggplot2,plotly,shiny,shinydashboard`
- **bioinformatics**: `Seurat,DESeq2,edgeR,limma`
- **genomics**: `GenomicRanges,AnnotationDbi,biomaRt,Seurat`
- **single-cell**: `Seurat,SingleCellExperiment,scater`

## Installation Commands

### Python (in Jupyter):
```python
!pip install <packages>
```

### R (in Jupyter):
```python
%%R
install.packages(c("<packages>"), repos="https://cran.rstudio.com/")
```

### R Bioconductor:
```python
%%R
if (!requireNamespace("BiocManager", quietly = TRUE))
    install.packages("BiocManager")
BiocManager::install(c("<packages>"))
```

## Examples

**User:** "I need packages for genomics analysis"
**Response:** 
```python
!pip install biopython pysam scanpy pandas numpy
```

**User:** "I need ggplot2"
**Response:**
```python
%%R
install.packages(c("ggplot2", "tidyverse"), repos="https://cran.rstudio.com/")
```

**User:** "Set me up for single-cell RNA-seq"
**Ask:** "Python (scanpy) or R (Seurat)?"
