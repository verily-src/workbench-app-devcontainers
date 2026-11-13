# Package Installation Assistant for Antigravity

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
- **statistics**: `scipy statsmodels pingouin pandas numpy`
- **geospatial**: `geopandas shapely folium pandas numpy`
- **nlp**: `transformers spacy nltk gensim pandas numpy`

### R
- **data science**: `tidyverse,dplyr,tidyr,readr,ggplot2`
- **visualization**: `ggplot2,plotly,shiny,shinydashboard`
- **bioinformatics**: `Seurat,DESeq2,edgeR,limma`
- **genomics**: `GenomicRanges,AnnotationDbi,biomaRt,Seurat`
- **single-cell**: `Seurat,SingleCellExperiment,scater`
- **statistics**: `lme4,nlme,survival,MASS`
- **time series**: `forecast,zoo,tseries`

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

**User:** "I need time series packages"
**Response:**
```python
!pip install prophet statsmodels pmdarima pandas numpy matplotlib
```

---

## Create a Custom App (Full Folder)

When the user asks to **create an app** with packages pre-installed (e.g. *"create me a JupyterLab
app with pandas and scikit-learn"*), don't just give an install command — **spit out a complete
app folder** they can commit under `workbench-app-devcontainers/src/<app-name>/` and point their
Workbench custom app config at.

### Why a whole folder

A Workbench app is a folder, not a single file. The `docker-compose.yaml` defines the
`application-server` container that runs the app (image, port, `app-network`, fuse mounts); the
startup scripts wire up bucket mounting. A lone `.devcontainer.json` will not launch the app.

### What to emit

A folder `src/<app-name>/` containing, each in its own labeled code block:

- `.devcontainer.json` — based on the app type's template, with the `common-packages` feature added
- `docker-compose.yaml` — from the template (correct image/port/user/network)
- `devcontainer-template.json` — app metadata (`id`/`name` = `<app-name>`, `cloud`/`login` options;
  Jupyter also gets `containerImage`/`containerPort`)
- `README.md` — short description + placement instructions
- `Dockerfile` — **VSCode only** (from `src/vscode/Dockerfile`)

Base each app on its existing template — read the real files from `src/<app>/`, don't hand-copy:

| App type | Template | image | port | user |
|----------|----------|-------|------|------|
| Jupyter / JupyterLab (default) | `src/jupyter-template/` | `${templateOption:containerImage}` (+ local `jupyter` feature) | 8888 | jupyter |
| RStudio / R / R Shiny | `src/r-analysis/` | `ghcr.io/rocker-org/devcontainer/tidyverse` | 8787 | rstudio |
| VSCode | `src/vscode/` | `lscr.io/linuxserver/code-server` (Dockerfile) | 8443 | abc |

### The package block (add to `.devcontainer.json` `features`)

```json
"ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
  "pythonPackages": "pandas numpy scikit-learn",
  "rPackages": "tidyverse,ggplot2"
}
```

- **Python** → `pythonPackages` (space-separated). **R / R Shiny** → `rPackages` (comma-separated,
  no spaces; `src/r-analysis` already installs `shiny,shinydashboard`).
- **VSCode extensions** are not pip/R packages — they go in the `Dockerfile` from open-vsx.
  `common-packages` only covers terminal Python/R libraries.

### Output rules

- Emit the whole folder in one response; keep `container_name: "application-server"` and
  `networks: app-network` (`external: true`) intact.
- Pick an app name from the request (user can rename).
- End with: *"Drop this folder into `workbench-app-devcontainers/src/<app-name>/`, push it, and
  point your custom app config at that folder."*
- Only ask when genuinely ambiguous (Python vs R for a domain; VSCode extensions vs libraries).

> The full worked example (a complete JupyterLab folder) lives in
> `skills/CREATE_CUSTOM_APP_WITH_PACKAGES.md` — follow the same shape.
