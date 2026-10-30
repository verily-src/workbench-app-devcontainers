# Install Packages (Natural Language)

**When to use:** User requests packages in natural language within a Jupyter, RStudio, or VSCode environment.

**Examples:**
- "I need ggplot2"
- "Install machine learning packages"
- "I want tools for genomics analysis"
- "Can you set up deep learning packages?"
- "Set me up for single-cell RNA-seq analysis"

---

## What This Skill Does

When a user requests packages, this skill:

1. **Parses** the natural language to identify packages
2. **Maps** domains (e.g., "machine learning") to package lists
3. **Generates** the appropriate installation command
4. **Provides** usage examples

---

## Two Approaches

### Approach 1: Pre-install Packages (Best for Known Needs)

Use the `common-packages` feature in `.devcontainer.json`:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "tensorflow scikit-learn pandas numpy matplotlib",
      "rPackages": "Seurat,DESeq2,ggplot2,tidyverse"
    }
  }
}
```

**When to use:** User knows packages upfront when creating the app.

### Approach 2: On-Demand Installation (Best for Exploratory Work)

Generate installation commands that users run in their environment:

**Python (in Jupyter):**
```python
!pip install scikit-learn xgboost pandas numpy matplotlib
```

**R (in Jupyter with R kernel or RStudio):**
```python
%%R
install.packages(c("ggplot2", "tidyverse"), repos="https://cran.rstudio.com/")
```

**When to use:** User realizes they need packages while working.

---

## Package Domain Mappings

### Python Domains

```
machine learning → scikit-learn xgboost lightgbm pandas numpy matplotlib
deep learning → tensorflow torch transformers keras pandas numpy matplotlib
nlp → transformers spacy nltk gensim pandas numpy
visualization → matplotlib seaborn plotly pandas numpy
bioinformatics → biopython scanpy anndata pandas numpy matplotlib
genomics → biopython pysam scanpy pandas numpy
single-cell → scanpy anndata leidenalg pandas numpy matplotlib
bigquery → google-cloud-bigquery google-cloud-storage db-dtypes pandas numpy
statistics → scipy statsmodels pingouin pandas numpy
time series → prophet statsmodels pmdarima pandas numpy matplotlib
geospatial → geopandas shapely folium pandas numpy
computer vision → opencv-python pillow scikit-image numpy
web scraping → beautifulsoup4 requests pandas
```

### R Domains

```
data science → tidyverse,dplyr,tidyr,readr,ggplot2
visualization → ggplot2,plotly,shiny,shinydashboard
machine learning → caret,randomForest,xgboost,mlr3
bioinformatics → Seurat,DESeq2,edgeR,limma
genomics → GenomicRanges,AnnotationDbi,biomaRt,Seurat
single-cell → Seurat,SingleCellExperiment,scater
statistics → lme4,nlme,survival,MASS
time series → forecast,zoo,tseries
bigquery → bigrquery,googleCloudStorageR
```

---

## How to Use This Skill

### Step 1: Identify Language

**Python indicators:**
- Mentions: "python", "pip", "jupyter", "numpy", "pandas", "tensorflow"
- Context: In `.ipynb` file or Jupyter environment
- Default for Jupyter apps

**R indicators:**
- Mentions: "R", "ggplot", "tidyverse", "Seurat", "rstudio"
- Explicitly says "R packages"

### Step 2: Map Natural Language to Packages

**Example 1:** "I need ggplot2"
- Language: R
- Packages: `tidyverse,ggplot2`

**Example 2:** "I need machine learning packages"
- Language: Python (default)
- Domain: machine learning
- Packages: `scikit-learn xgboost lightgbm pandas numpy matplotlib`

**Example 3:** "Install tools for single-cell analysis"
- Ask: "Python (scanpy) or R (Seurat)?"
- Python: `scanpy anndata leidenalg pandas numpy matplotlib`
- R: `Seurat,SingleCellExperiment,scater,tidyverse`

### Step 3: Generate Installation Command

**For Python (in Jupyter):**
```python
!pip install scikit-learn xgboost lightgbm pandas numpy matplotlib
```

**For R (in Jupyter with %%R magic):**
```python
%%R
install.packages(c("ggplot2", "tidyverse"), repos="https://cran.rstudio.com/")
```

**For R (in RStudio):**
```r
install.packages(c("ggplot2", "tidyverse"), repos="https://cran.rstudio.com/")
```

**For R Bioconductor packages:**
```python
%%R
if (!requireNamespace("BiocManager", quietly = TRUE))
    install.packages("BiocManager")
BiocManager::install(c("DESeq2", "edgeR", "limma"))
```

### Step 4: Provide Usage Examples

After showing the installation command, provide import/usage examples:

**Python:**
```python
import pandas as pd
import numpy as np
from sklearn import ...
```

**R:**
```r
library(ggplot2)
library(tidyverse)
```

---

## Complete Examples

### Example 1: User says "I need ggplot2"

**Response:**

```markdown
I'll help you install ggplot2. Run this in a notebook cell:

\`\`\`python
%%R
install.packages(c("ggplot2", "tidyverse"), repos="https://cran.rstudio.com/")
\`\`\`

After installation, use it in R cells:
\`\`\`r
library(ggplot2)
ggplot(data, aes(x=x, y=y)) + geom_point()
\`\`\`
```

### Example 2: User says "Set me up for deep learning"

**Response:**

```markdown
I'll install deep learning packages. Run this:

\`\`\`python
!pip install tensorflow torch transformers keras pandas numpy matplotlib
\`\`\`

This installs:
- TensorFlow and PyTorch (frameworks)
- Transformers (NLP models)
- pandas, numpy (data handling)
- matplotlib (visualization)

Import them:
\`\`\`python
import tensorflow as tf
import torch
import pandas as pd
import numpy as np
\`\`\`
```

### Example 3: User says "I need packages for genomics analysis"

**Response:**

```markdown
For genomics analysis, which would you prefer?

**Python (scanpy)** - best for single-cell RNA-seq:
\`\`\`python
!pip install scanpy anndata biopython pysam pandas numpy matplotlib
\`\`\`

**R (Seurat/Bioconductor)** - best for bulk RNA-seq and single-cell:
\`\`\`python
%%R
if (!requireNamespace("BiocManager", quietly = TRUE))
    install.packages("BiocManager")
BiocManager::install(c("Seurat", "DESeq2", "GenomicRanges", "AnnotationDbi"))
\`\`\`

Let me know which you prefer, or I can set up both!
```

### Example 4: User says "I want BigQuery packages"

**Response:**

```markdown
I'll install Google Cloud BigQuery packages:

\`\`\`python
!pip install google-cloud-bigquery google-cloud-storage db-dtypes pandas numpy
\`\`\`

Example usage:
\`\`\`python
from google.cloud import bigquery
import pandas as pd

client = bigquery.Client()
query = "SELECT * FROM \`project.dataset.table\` LIMIT 100"
df = client.query(query).to_dataframe()
\`\`\`
```

---

## Special Cases

### Bioconductor Packages (R)

Packages like DESeq2, edgeR, limma require BiocManager:

```python
%%R
if (!requireNamespace("BiocManager", quietly = TRUE))
    install.packages("BiocManager")
BiocManager::install(c("DESeq2", "edgeR", "limma"))
```

### GPU/CUDA Packages

If user mentions GPU:

```python
# PyTorch with CUDA 11.8
!pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# TensorFlow GPU
!pip install tensorflow-gpu
```

### Package Versions

If user specifies versions:

```python
!pip install tensorflow==2.13.0 pandas==1.5.0
```

### Package Aliases

Handle common aliases:
- "sklearn" → "scikit-learn"
- "cv2" → "opencv-python"
- "tf" → "tensorflow"
- "bs4" → "beautifulsoup4"

---

## Creating Apps with Pre-installed Packages

When the user wants to **create a new app** with packages, don't emit a lone `.devcontainer.json` —
a Workbench app is a **folder** (`.devcontainer.json` + `docker-compose.yaml` +
`devcontainer-template.json`, plus a `Dockerfile` for VSCode). A single `.devcontainer.json` will
not launch the app.

**Follow `CREATE_CUSTOM_APP_WITH_PACKAGES.md`**, which spits out the complete app folder for the
requested type (Jupyter / RStudio-Shiny / VSCode) with the `common-packages` feature injected,
ready to commit under `src/<app-name>/` and point a custom app config at.

Use the domain→package mappings above to turn a vague request ("machine learning packages") into a
concrete list, then hand off to that skill to generate the folder.

---

## Error Handling

### Unknown Package

```markdown
I couldn't find a package called "xyzabc". Did you mean:
- xgboost (machine learning)
- ...

Or describe what you're trying to do (e.g., "analyze genomics data")
```

### Ambiguous Request

```markdown
I can help install packages! What type of analysis?

- Machine learning / AI
- Data visualization
- Bioinformatics / genomics
- Statistics
- (or tell me specific packages)
```

### Installation Failure

```markdown
Installation failed. Try:
1. Install packages one at a time
2. Check write permissions
3. Try: \`!pip install --user <package>\`
```

---

## Decision Tree

```
User requests packages
│
├─ Creating new app?
│  └─ Generate .devcontainer.json with common-packages feature
│
├─ Working in existing environment?
│  │
│  ├─ Explicit packages? (e.g., "ggplot2", "tensorflow")
│  │  └─ Generate pip/R install command
│  │
│  └─ Domain mentioned? (e.g., "machine learning")
│     ├─ Map to package list
│     ├─ Identify language (Python/R)
│     └─ Generate install command
│
└─ Too vague?
   └─ Ask clarifying question
```

---

## Summary

This skill enables **natural language package installation** by:

1. **Parsing** user intent (domain/task identification)
2. **Mapping** to curated package lists
3. **Generating** installation commands
4. **Providing** usage examples

**Key principle:** Make it easy to request packages without knowing exact names, while supporting explicit package specifications.

**Two modes:**
- **Pre-install** (common-packages feature) - for app creation
- **On-demand** (pip/R commands) - for exploratory work
