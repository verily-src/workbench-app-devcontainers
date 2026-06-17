# Create R Analysis App with Custom Packages

**When to use:** User wants to create an R Analysis environment with specific packages pre-installed (e.g., "I want R with tidyverse, ggplot2, and plotly").

**Goal:** Generate a complete devcontainer directory that pre-installs the requested R packages.

---

## What to Generate

Create a directory with these files:

### 1. `.devcontainer.json`

```json
{
  "name": "R Analysis - Custom Packages",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "postCreateCommand": [
    "./startupscript/post-startup.sh",
    "rstudio",
    "/home/rstudio",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "postStartCommand": [
    "./startupscript/remount-on-restart.sh",
    "rstudio",
    "/home/rstudio",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "features": {
    "ghcr.io/devcontainers/features/java": {
      "version": "17"
    },
    "ghcr.io/devcontainers/features/aws-cli": {},
    "ghcr.io/dhoeric/features/google-cloud-cli": {},
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "USER_PACKAGES_HERE"
    }
  },
  "remoteUser": "root"
}
```

**Replace `USER_PACKAGES_HERE` with:** Comma-separated list (NO SPACES) of user's requested packages

### 2. `docker-compose.yaml`

```yaml
services:
  app:
    container_name: "application-server"
    image: "ghcr.io/rocker-org/devcontainer/tidyverse:latest"
    restart: always
    volumes:
      - .:/workspace:cached
      - work:/home/rstudio:cached
    tmpfs:
      - /home/rstudio/workspace:uid=1000,gid=1000
    ports:
      - "8787:8787"
    environment:
      "DISABLE_AUTH": "true"
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
networks:
  app-network:
    external: true
volumes:
  work:
```

### 3. `README.md`

```markdown
# R Analysis - Custom Packages

## Pre-installed Packages

[LIST THE PACKAGES]

## How to Deploy

1. Push this directory to a GitHub repository
2. In Workbench, create a Custom App
3. Point to this directory
4. Launch - packages will be ready

## Verify Installation

Once launched, run in R console:
```r
library(PACKAGE_NAME)
```
```

### 4. `devcontainer-template.json`

```json
{
  "id": "r-analysis-custom",
  "version": "1.0.0",
  "name": "R Analysis - Custom Packages",
  "description": "R Analysis with pre-installed packages",
  "type": "application",
  "featureSet": "full"
}
```

---

## Example Interaction

**User:** "I want an R analysis environment with tidyverse, ggplot2, plotly, and shiny"

**Claude:**
1. Create directory structure
2. Generate `.devcontainer.json` with:
   ```json
   "rPackages": "tidyverse,ggplot2,plotly,shiny"
   ```
3. Generate other files
4. Tell user how to deploy

---

## Important Notes

- **Package format:** Comma-separated, NO SPACES (e.g., `"pkg1,pkg2,pkg3"`)
- **Common packages:** tidyverse, ggplot2, dplyr, plotly, shiny, data.table, caret, randomForest, bigrquery, googleCloudStorageR
- **Use the feature:** `ghcr.io/verily-src/workbench-app-devcontainers/common-packages`
- User can also add Python packages with `"pythonPackages": "pandas numpy"` if needed

---

## Alternative: For Advanced Users

If user wants MORE control, suggest using the `r-packages` feature directly:

```json
{
  "features": {
    "ghcr.io/rocker-org/devcontainer-features/r-packages": {
      "packages": "tidyverse,ggplot2,plotly,shiny",
      "installSystemRequirements": true
    }
  }
}
```

But default to the `common-packages` feature for simplicity.
