# Pre-installing Packages in Workbench Apps

Users often want specific packages pre-installed in their apps to avoid running `pip install` or `install.packages()` every time. This guide shows two simple approaches.

---

## Approach 1: Natural Language with Claude (Easiest!)

Just ask Claude what you need, and it will help you install packages:

**Examples:**
- "I need ggplot2"
- "Set me up for machine learning"
- "I want tools for genomics analysis"
- "Install deep learning packages"

Claude understands natural language and will either:
- Generate an installation command for you to run
- Pre-configure your app with the packages

**Supported domains:**
- Machine Learning, Deep Learning, NLP
- Data Visualization, Dashboards  
- Bioinformatics, Genomics, Single-cell
- BigQuery/GCP, Statistics, Time Series
- And more...

---

## Approach 2: Pre-install with common-packages Feature

Use the built-in `common-packages` feature in your `.devcontainer.json`:

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

**Python packages:** Space-separated  
**R packages:** Comma-separated (NO SPACES)

**When to use this:**
- You know exactly which packages you need
- You want packages available immediately at app startup
- You're creating a new app

See [`features/src/common-packages/README.md`](features/src/common-packages/README.md) for details.

---

## Complete Examples

### Example 1: Jupyter with Machine Learning Packages

**With Claude:**
Just say: "Create a Jupyter app for machine learning"

**Manual configuration:**
```json
{
  "name": "Jupyter - Machine Learning",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "scikit-learn xgboost tensorflow torch pandas numpy matplotlib"
    }
  }
}
```

### Example 2: R Analysis for Genomics

**With Claude:**
Just say: "I need R packages for genomics analysis"

**Manual configuration:**
```json
{
  "name": "R Analysis - Genomics",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "Seurat,DESeq2,GenomicRanges,tidyverse,ggplot2"
    }
  }
}
```

### Example 3: On-Demand Installation (Already in Jupyter)

If you're already working and realize you need more packages:

**Ask Claude:** "I need plotly for visualization"

**Claude will show you:**
```python
!pip install plotly
```

Or for R:
```python
%%R
install.packages("plotly")
```

---

## Comparison

| Approach | When Available | Requires Rebuild | Natural Language |
|----------|---------------|------------------|------------------|
| **Ask Claude** | On-demand or pre-build | No (on-demand) / Yes (pre-build) | ✅ Yes |
| **common-packages feature** | At app startup | Yes | ❌ No |

**Best practice:** 
- Use `common-packages` for packages you know you'll need
- Ask Claude when you discover new needs while working

---

## Common Package Lists

### Python

**Data Science:** pandas, numpy, scipy, matplotlib, seaborn  
**Machine Learning:** scikit-learn, xgboost, lightgbm  
**Deep Learning:** tensorflow, torch, transformers, keras  
**NLP:** transformers, spacy, nltk, gensim  
**Bioinformatics:** biopython, scanpy, anndata  
**BigQuery:** google-cloud-bigquery, google-cloud-storage, db-dtypes  
**Visualization:** matplotlib, seaborn, plotly, dash, streamlit

### R

**Core Data Science:** tidyverse, dplyr, tidyr, readr, ggplot2  
**Visualization:** ggplot2, plotly, shiny, shinydashboard  
**Machine Learning:** caret, randomForest, xgboost  
**Bioinformatics:** Seurat, DESeq2, edgeR, limma  
**Genomics:** GenomicRanges, AnnotationDbi, biomaRt  
**BigQuery:** bigrquery, googleCloudStorageR

---

## FAQ

### Q: How do I install packages I discover I need while working?

**A:** Just ask Claude! Say "I need <package>" or "I need tools for <task>", and Claude will generate the installation command for you.

### Q: Can I use both Python and R packages?

**A:** Yes! Just specify both:
```json
{
  "pythonPackages": "pandas numpy",
  "rPackages": "ggplot2,tidyverse"
}
```

### Q: What if I need a package that's not in the common lists?

**A:** Just ask Claude or add it explicitly to the `pythonPackages` or `rPackages` field. For example:
- "I need the 'polars' package"
- Or add: `"pythonPackages": "polars duckdb"`

### Q: How do I install Bioconductor packages?

**A:** Ask Claude "I need Bioconductor packages for RNA-seq", or use:
```json
{
  "rPackages": "BiocManager,DESeq2,edgeR,limma"
}
```

The `common-packages` feature automatically handles Bioconductor installation.

---

## Summary

**Easiest way:** Ask Claude in natural language  
**For known needs:** Use `common-packages` feature in `.devcontainer.json`  
**Both work together:** Pre-install common packages, ask Claude for additional ones

No more manual `pip install` or `install.packages()` every time! 🎉
