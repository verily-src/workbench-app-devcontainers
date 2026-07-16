# Create Custom App with Pre-installed Packages

**When to use:** A customer wants a Workbench app (JupyterLab, etc.) with specific packages pre-installed, and wants a devcontainer config they can point their **custom app config** at.

**User story:** A customer on their private workstation says *"I need a JupyterLab app with these packages pre-installed."* The skill's output is a single `.devcontainer.json` they paste into their custom app config in Workbench.

**Examples:**
- "I need a JupyterLab app with pandas, numpy, and scikit-learn"
- "Give me a Jupyter app with tidyverse and ggplot2"
- "Jupyter with tensorflow, torch, and R's caret"

**Goal:** Emit a single, complete, self-contained `.devcontainer.json` that both **runs the app** (via the prebuilt app image) **and** pre-installs the requested packages (via the `common-packages` feature).

---

## Output Contract (READ FIRST)

When the user names their packages, respond with **exactly one thing: a single `.devcontainer.json` fenced code block.**

- **One file, self-contained.** It references a published image + a published feature by their `ghcr.io/...` paths. No `docker-compose.yaml`, no `Dockerfile`, no `startupscript/`, no local `./.devcontainer/...` paths. The customer doesn't have the repo — the file must work on its own.
- **One output.** Emit the whole config in a single message. Don't split it across sections or stream it in pieces.
- **No follow-up questions** when the packages and app type are given. Just generate. (Only exception: genuinely ambiguous language — see "When to Ask".)
- **Copy-pasteable.** Valid JSON, no comments, no unfilled placeholders.

Keep prose around the block to a one-line lead-in plus a one-line "paste this into your custom app config" note. The code block is the deliverable.

---

## The Template (canonical output)

Base image runs the app; the `common-packages` feature installs the packages. Fill in `pythonPackages` and/or `rPackages`; drop whichever the user didn't ask for.

```json
{
  "name": "JupyterLab - Custom Packages",
  "image": "ghcr.io/verily-src/workbench-app-devcontainers/jupyter:latest",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "SPACE_SEPARATED_PYTHON_PACKAGES",
      "rPackages": "COMMA_SEPARATED_R_PACKAGES"
    }
  }
}
```

- **Base image** `ghcr.io/verily-src/workbench-app-devcontainers/jupyter:latest` is the prebuilt Workbench JupyterLab app — it already launches JupyterLab, so no compose/startup wiring is needed in the customer's file.
- **`common-packages`** is referenced by its **ghcr path** (never `./.devcontainer/features/common-packages` — that local path only resolves inside the repo, not in the customer's standalone config).

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

Include only the key(s) the user asked for. Python-only → omit `rPackages`. R-only → omit `pythonPackages`.

---

## Example: Python packages

**User:** "I need a JupyterLab app with pandas, numpy, and scikit-learn"

**Generate:**

`.devcontainer.json` — paste this into your custom app config:
```json
{
  "name": "JupyterLab - Custom Packages",
  "image": "ghcr.io/verily-src/workbench-app-devcontainers/jupyter:latest",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy scikit-learn"
    }
  }
}
```

---

## Example: R packages

**User:** "Give me a Jupyter app with tidyverse and ggplot2"

**Generate:**

`.devcontainer.json` — paste this into your custom app config:
```json
{
  "name": "JupyterLab - Custom Packages",
  "image": "ghcr.io/verily-src/workbench-app-devcontainers/jupyter:latest",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "tidyverse,ggplot2"
    }
  }
}
```

---

## Example: Both Python and R

**User:** "Jupyter with pandas and numpy, plus R's ggplot2 and dplyr"

**Generate:**

`.devcontainer.json` — paste this into your custom app config:
```json
{
  "name": "JupyterLab - Custom Packages",
  "image": "ghcr.io/verily-src/workbench-app-devcontainers/jupyter:latest",
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy",
      "rPackages": "ggplot2,dplyr"
    }
  }
}
```

---

## When to Ask (the only exception to "no questions")

Only pause to ask if the language is genuinely ambiguous — e.g. "set me up for single-cell analysis" maps to both Python (`scanpy`) and R (`Seurat`). Ask which they want, then emit the single `.devcontainer.json`. If the user names concrete packages, never ask — just generate.

For mapping vague domains ("machine learning", "genomics") to concrete package lists, see `INSTALL_PACKAGES.md`.

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
