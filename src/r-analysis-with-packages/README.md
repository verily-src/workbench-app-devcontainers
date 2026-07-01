# R Analysis with Pre-installed Packages (TEST APP)

This is a test app to demonstrate the `common-packages` feature.

## What's Pre-installed

These R packages are pre-installed and ready to use:

- **tidyverse** - Data science ecosystem
- **ggplot2, dplyr, tidyr, readr** - Data manipulation & visualization
- **plotly** - Interactive plots
- **shiny, shinydashboard** - Web apps
- **DT** - Interactive tables
- **data.table** - Fast data operations
- **caret, randomForest** - Machine learning
- **bigrquery, googleCloudStorageR** - Google Cloud integration
- **arrow** - Apache Arrow

## How to Test

1. Deploy this app from the `package-installation` branch
2. Launch RStudio
3. Run in R console:
   ```r
   library(tidyverse)
   library(ggplot2)
   library(plotly)
   
   # Should all load without needing install.packages()
   ```

## How It Works

The `.devcontainer.json` includes:

```json
{
  "features": {
    "../../features/src/common-packages": {
      "rPackages": "tidyverse,ggplot2,dplyr,tidyr,readr,plotly,shiny,shinydashboard,DT,data.table,caret,randomForest,bigrquery,googleCloudStorageR,arrow"
    }
  }
}
```

All packages are installed during the app build, so they're ready immediately when you launch.

## Deployment Instructions

1. In Workbench, create a Custom App
2. Repository: Your fork of `workbench-app-devcontainers`
3. Branch: `package-installation`
4. Path: `src/r-analysis-with-packages`
5. Launch and verify packages are pre-installed
