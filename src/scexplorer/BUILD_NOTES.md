# Build-Time Installation Summary

## What happens during `docker build`:

1. **Base Image**: `ghcr.io/rocker-org/devcontainer/tidyverse:4.5`
   - Includes R 4.5, tidyverse, and RStudio Server

2. **System Dependencies** (apt packages):
   - HDF5, SSL, XML, PNG, Git, Cairo, GLPK libraries
   - Required for single-cell analysis packages

3. **R Package Installation**:
   - BiocManager (for Bioconductor packages)
   - remotes (for GitHub packages)
   - All CRAN packages scExploreR depends on (~30 packages)
   - Bioconductor packages (HDF5Array)
   - GitHub packages (presto, SCUBA, scDE)
   - **scExploreR itself** from `amc-heme/scExploreR`

4. **Files Copied into Image**:
   - `launch-scexplorer.R` → `/usr/local/bin/`
   - `config-template.yaml` → `/usr/local/share/scexplorer/`
   - `entrypoint.sh` → `/usr/local/bin/`

5. **Entrypoint**: `/usr/local/bin/entrypoint.sh`
   - Executes `launch-scexplorer.R` to start scExploreR

## What happens at runtime:

- `postCreateCommand`: Runs Workbench setup scripts (gcsfuse, CLI tools)
- `postStartCommand`: Re-mounts GCS buckets
- Container CMD: Launches scExploreR web app on port 3838

## File Layout:

```
Built into image:
  /usr/local/bin/entrypoint.sh
  /usr/local/bin/launch-scexplorer.R
  /usr/local/share/scexplorer/config-template.yaml
  /usr/local/lib/R/site-library/scExploreR/  (installed package)

Volume mounted (writable):
  /workspace/  (contains app source, config.yaml)
  /home/rstudio/  (user home, GCS mount point)
```

## Build Time:

Expect Docker build to take **15-20 minutes** due to:
- Installing ~40+ R packages from source
- Compiling C/C++ code in packages like Seurat, HDF5Array
- GitHub package installations

Build time only happens once (or when image needs rebuild).
