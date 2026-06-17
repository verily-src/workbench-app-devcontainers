# Pre-installing Packages in Workbench Apps

Users often want specific packages pre-installed in their apps to avoid running `pip install` or `install.packages()` every time they create an app. This guide shows three approaches.

---

## Approach 1: Devcontainer Features (Easiest for R)

### R Packages

Use the `r-packages` feature in `.devcontainer.json`:

```json
{
  "name": "R Analysis with Custom Packages",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "features": {
    "ghcr.io/rocker-org/devcontainer-features/r-packages": {
      "packages": "tidyverse,ggplot2,dplyr,plotly,shiny,data.table,caret,randomForest,xgboost,keras,reticulate,bigrquery,googleCloudStorageR,arrow,jsonlite,httr",
      "installSystemRequirements": true
    }
  }
}
```

**Supported options:**
- `packages`: Comma-separated list (no spaces!)
- `installSystemRequirements`: Auto-install system deps (recommended: `true`)
- `additionalRepositories`: Add custom R repos (e.g., Bioconductor)

**Example with Bioconductor:**

```json
{
  "features": {
    "ghcr.io/rocker-org/devcontainer-features/r-packages": {
      "packages": "BiocManager,DESeq2,edgeR,limma",
      "installSystemRequirements": true,
      "additionalRepositories": "bioc = 'https://bioconductor.org/packages/3.17/bioc'"
    }
  }
}
```

---

## Approach 2: Custom Dockerfile (Best for Python)

### Python Packages

Modify the app's `Dockerfile` to install packages during image build:

**Example: Jupyter with Data Science Packages**

```dockerfile
FROM jupyter/scipy-notebook:python-3.11

USER root

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# Install Python packages
RUN pip install --no-cache-dir \
    pandas==2.1.4 \
    numpy==1.26.2 \
    scikit-learn==1.3.2 \
    matplotlib==3.8.2 \
    seaborn==0.13.0 \
    plotly==5.18.0 \
    jupyter-dash==0.4.2 \
    google-cloud-bigquery==3.14.0 \
    google-cloud-storage==2.14.0 \
    db-dtypes==1.2.0 \
    sqlalchemy==2.0.23 \
    psycopg2-binary==2.9.9 \
    tensorflow==2.15.0 \
    torch==2.1.1 \
    transformers==4.36.0

# Install JupyterLab extensions (optional)
RUN jupyter labextension install @jupyter-widgets/jupyterlab-manager
```

**Best practices:**
- Pin versions for reproducibility (`package==1.2.3`)
- Use `--no-cache-dir` to reduce image size
- Group related packages in single `RUN` command
- Install heavy packages like TensorFlow/PyTorch early (better layer caching)

---

## Approach 3: Post-Create Script (Most Flexible)

Use `postCreateCommand` in `.devcontainer.json` to run installation after container starts:

### Create installation script

**`install-packages.sh`:**

```bash
#!/bin/bash
set -e

echo "Installing custom packages..."

# Python packages (if using Jupyter/Python)
if command -v pip &> /dev/null; then
    pip install --no-cache-dir -r /workspace/requirements.txt
fi

# R packages (if using R)
if command -v R &> /dev/null; then
    R --quiet -e "
    packages <- c(
        'tidyverse', 'ggplot2', 'dplyr', 'plotly', 'shiny',
        'data.table', 'caret', 'randomForest', 'xgboost'
    )
    install.packages(packages, repos='https://cran.rstudio.com/', quiet=TRUE)
    "
fi

echo "Package installation complete!"
```

### Update `.devcontainer.json`

```json
{
  "name": "Custom App with Pre-installed Packages",
  "postCreateCommand": "bash /workspace/install-packages.sh"
}
```

**Pros:**
- ✅ Flexible - can install from multiple sources
- ✅ Can read from `requirements.txt` or `DESCRIPTION` file
- ✅ Easy to version control

**Cons:**
- ❌ Runs every time container is created (slower startup)
- ❌ Not cached in image layers

---

## Comparison Table

| Approach | Best For | Speed | Complexity | Reproducibility |
|----------|----------|-------|------------|-----------------|
| **Devcontainer Feature** | R packages | ⚡⚡⚡ Fast | ⭐ Easy | ⭐⭐⭐ Excellent |
| **Custom Dockerfile** | Python packages | ⚡⚡⚡ Fast | ⭐⭐ Medium | ⭐⭐⭐ Excellent |
| **Post-Create Script** | Mixed/Dynamic | ⚡ Slow | ⭐⭐ Medium | ⭐⭐ Good |

---

## Complete Examples

### Example 1: R Analysis with 15 Common Packages

**`.devcontainer.json`:**

```json
{
  "name": "R Analysis - Data Science",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "features": {
    "ghcr.io/rocker-org/devcontainer-features/r-packages": {
      "packages": "tidyverse,ggplot2,dplyr,tidyr,readr,stringr,lubridate,purrr,data.table,plotly,shiny,shinydashboard,DT,bigrquery,googleCloudStorageR",
      "installSystemRequirements": true
    }
  }
}
```

### Example 2: Jupyter with ML/AI Stack

**`Dockerfile`:**

```dockerfile
FROM jupyter/datascience-notebook:python-3.11

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# Core data science
RUN pip install --no-cache-dir \
    pandas==2.1.4 numpy==1.26.2 scipy==1.11.4 \
    scikit-learn==1.3.2 xgboost==2.0.3 lightgbm==4.1.0

# Visualization
RUN pip install --no-cache-dir \
    matplotlib==3.8.2 seaborn==0.13.0 plotly==5.18.0

# Deep learning
RUN pip install --no-cache-dir \
    tensorflow==2.15.0 torch==2.1.1 transformers==4.36.0

# Google Cloud
RUN pip install --no-cache-dir \
    google-cloud-bigquery==3.14.0 \
    google-cloud-storage==2.14.0 \
    db-dtypes==1.2.0
```

### Example 3: Hybrid R + Python (Post-Create)

**`requirements.txt`:**

```
pandas>=2.0.0
numpy>=1.24.0
google-cloud-bigquery>=3.10.0
```

**`install-packages.sh`:**

```bash
#!/bin/bash
set -e

# Python
pip install --no-cache-dir -r /workspace/requirements.txt

# R
R --quiet -e "install.packages(c('reticulate', 'bigrquery', 'ggplot2'), repos='https://cran.rstudio.com/')"
```

**`.devcontainer.json`:**

```json
{
  "postCreateCommand": "bash /workspace/install-packages.sh"
}
```

---

## FAQ

### Q: Which approach should I use?

- **R packages only** → Devcontainer feature (Approach 1)
- **Python packages only** → Custom Dockerfile (Approach 2)
- **Mixed R + Python** → Post-create script (Approach 3)
- **User-specific customization** → Post-create script (Approach 3)

### Q: Can I combine approaches?

Yes! For example:

```json
{
  "features": {
    "ghcr.io/rocker-org/devcontainer-features/r-packages": {
      "packages": "tidyverse,ggplot2"
    }
  },
  "postCreateCommand": "pip install -r /workspace/requirements.txt"
}
```

### Q: How do I test my package list?

1. Create app in Workbench with your config
2. Launch the app
3. Verify packages are installed:
   - Python: `pip list` or `import package_name`
   - R: `installed.packages()` or `library(package_name)`

### Q: Packages are installing every time - how do I cache them?

**Move from post-create script to Dockerfile!** Dockerfile changes are cached in image layers. Post-create scripts run every container creation.

### Q: Can users add their own packages later?

Yes! Users can always run:
- Python: `pip install mypackage`
- R: `install.packages("mypackage")`

Pre-installed packages are just defaults. Users retain full control.

---

## Template: Create Your Own Custom App Config

```json
{
  "name": "My Custom Research Environment",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "features": {
    // For R packages
    "ghcr.io/rocker-org/devcontainer-features/r-packages": {
      "packages": "PACKAGE1,PACKAGE2,PACKAGE3",
      "installSystemRequirements": true
    },
    // Cloud tools
    "ghcr.io/dhoeric/features/google-cloud-cli": {},
    "ghcr.io/devcontainers/features/aws-cli": {}
  },
  // For Python packages or complex installs
  "postCreateCommand": "bash /workspace/install-custom-packages.sh",
  "remoteUser": "root"
}
```

---

## Next Steps

1. Choose your approach based on the table above
2. Copy one of the complete examples
3. Customize package list for your use case
4. Test in a Workbench workspace
5. Share the config with your team!

**Questions?** File an issue at https://github.com/verily-src/workbench-app-devcontainers
