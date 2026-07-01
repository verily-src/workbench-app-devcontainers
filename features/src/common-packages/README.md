# Pre-install Packages Feature

Pre-install your Python and R packages so you don't have to run `pip install` or `install.packages()` every time you create an app.

## Usage

Just list the packages you want in your `.devcontainer.json`:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy scikit-learn matplotlib",
      "rPackages": "tidyverse,ggplot2,dplyr,plotly,shiny"
    }
  }
}
```

That's it! Packages will be pre-installed when the app is built.

## Examples

### R Analysis with 15 packages

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "tidyverse,ggplot2,dplyr,tidyr,readr,plotly,shiny,DT,data.table,caret,randomForest,bigrquery,googleCloudStorageR,arrow,lubridate"
    }
  }
}
```

### Jupyter with Python packages

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy matplotlib seaborn scikit-learn google-cloud-bigquery google-cloud-storage"
    }
  }
}
```

### Both Python and R

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy",
      "rPackages": "ggplot2,dplyr"
    }
  }
}
```

## Format

- **Python packages:** Space-separated (e.g., `"pandas numpy scikit-learn"`)
- **R packages:** Comma-separated (e.g., `"tidyverse,ggplot2,dplyr"`)

## How It Works

- Packages install during container build (one-time)
- Apps launch instantly with packages ready
- Users can still install more packages at runtime if needed
- Much simpler than creating custom app configs

## Performance

- **First build:** Takes time to install packages
- **Every app after:** Instant - packages already there
- **vs. manual install every time:** Saves 5-10 minutes per app launch
