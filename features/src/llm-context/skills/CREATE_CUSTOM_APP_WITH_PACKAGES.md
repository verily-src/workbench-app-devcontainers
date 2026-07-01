# Create Custom App with Pre-installed Packages

**When to use:** User wants any app type (R Analysis, Jupyter, VSCode, etc.) with specific packages pre-installed.

**Examples:**
- "I want R with tidyverse and ggplot2"
- "I want Jupyter with pandas, numpy, and scikit-learn"
- "I want VSCode with tensorflow and torch"

**Goal:** Generate a complete devcontainer directory that pre-installs the requested packages.

---

## Package Format

**Python packages:** Space-separated
```json
"pythonPackages": "pandas numpy scikit-learn"
```

**R packages:** Comma-separated (NO SPACES)
```json
"rPackages": "tidyverse,ggplot2,dplyr"
```

**Both:**
```json
{
  "pythonPackages": "pandas numpy",
  "rPackages": "ggplot2,dplyr"
}
```

---

## Key Points

- **Works for ANY app type**: R Analysis, Jupyter, VSCode, RStudio, etc.
- **Any packages**: Users specify their own list - not limited to presets
- **During build**: Packages install once, available instantly after
- **User's repo**: Output can go anywhere, not just workbench-app-devcontainers

---

## How to Generate

Use the `common-packages` feature in `.devcontainer.json`:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "USER_PACKAGES_HERE",
      "rPackages": "USER_PACKAGES_HERE"
    }
  }
}
```

---

## Example: Jupyter with Python Packages

**User:** "I want Jupyter with pandas, numpy, and scikit-learn"

**Generate:**

`.devcontainer.json`:
```json
{
  "name": "Jupyter - Custom Packages",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy scikit-learn"
    }
  }
}
```

---

## Example: R Analysis with R Packages

**User:** "I want R with tidyverse and ggplot2"

**Generate:**

`.devcontainer.json`:
```json
{
  "name": "R Analysis - Custom Packages",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "tidyverse,ggplot2"
    }
  }
}
```

---

## Example: VSCode with Both

**User:** "I want VSCode with Python and R packages"

**Generate:**

`.devcontainer.json`:
```json
{
  "name": "VSCode - Custom Packages",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy",
      "rPackages": "ggplot2,dplyr"
    }
  }
}
```

---

## Common Packages Reference

**Python:**
- Data: pandas, numpy, scipy
- ML: scikit-learn, tensorflow, torch, transformers, xgboost
- Viz: matplotlib, seaborn, plotly
- Cloud: google-cloud-bigquery, google-cloud-storage

**R:**
- Core: tidyverse, ggplot2, dplyr, tidyr, readr
- Viz: plotly, shiny, shinydashboard
- ML: caret, randomForest, xgboost
- Cloud: bigrquery, googleCloudStorageR
