# Common Data Science Packages Feature

Pre-install common Python and R packages so users don't have to run `pip install` or `install.packages()` every time they create an app.

## Usage

Add this feature to your `.devcontainer.json`:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "basic",
      "rPackages": "basic"
    }
  }
}
```

## Package Presets

### Python Presets

**`basic`** (Default for Jupyter apps):
- pandas, numpy, matplotlib, seaborn, scikit-learn
- jupyter, ipywidgets
- google-cloud-bigquery, google-cloud-storage, db-dtypes

**`ml`** (Machine Learning):
- Everything in `basic` +
- tensorflow, torch, transformers
- xgboost, lightgbm, optuna, mlflow

**`bio`** (Bioinformatics):
- Everything in `basic` +
- biopython, scanpy, anndata, pysam

**`full`** (Everything):
- All packages above +
- plotly, dash, streamlit

### R Presets

**`basic`** (Default for R Analysis apps):
- tidyverse, ggplot2, dplyr, tidyr, readr
- plotly, shiny, DT
- bigrquery, googleCloudStorageR

**`ml`** (Machine Learning):
- Everything in `basic` +
- caret, randomForest, xgboost, keras, reticulate

**`bio`** (Bioinformatics):
- Everything in `basic` +
- Seurat, BiocManager, DESeq2

**`full`** (Everything):
- All packages above +
- data.table, arrow, sparklyr, shinydashboard

## Custom Packages

Add your own packages on top of presets:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "basic",
      "customPythonPackages": "mypackage anotherpackage",
      "rPackages": "basic",
      "customRPackages": "myRpackage,anotherRpackage"
    }
  }
}
```

**Note:** 
- Python custom packages are **space-separated**
- R custom packages are **comma-separated**

## Examples

### Jupyter with ML packages

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "ml"
    }
  }
}
```

### R Analysis with tidyverse + your packages

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "basic",
      "customRPackages": "zoo,forecast,prophet"
    }
  }
}
```

### Both Python and R (for RStudio with Python)

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "basic",
      "rPackages": "ml"
    }
  }
}
```

## Skip Everything (No Packages)

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "none",
      "rPackages": "none"
    }
  }
}
```

## How It Works

- Packages are installed during container build (one-time cost)
- Once built, apps launch instantly with packages ready
- Users can still install additional packages at runtime
- All system dependencies are handled automatically

## Performance

- **First build:** Slower (installs all packages)
- **Subsequent builds:** Fast (cached in image layers)
- **App launch:** Instant (packages already installed)

vs. installing manually every time:
- ❌ Manual: 5-10 min every app launch
- ✅ This feature: 0 seconds (already there)
