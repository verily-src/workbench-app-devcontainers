# Create Custom App with Pre-installed Packages

**When to use:** A customer wants a custom Workbench app (JupyterLab, RStudio / R Shiny, VSCode)
with specific Python and/or R packages pre-installed.

**User story:** *"Hey Claude, create me a custom app that has the packages I need — whatever
Python or R packages, R Shiny, etc."*

**Goal:** Spit out a **complete app folder** — `devcontainer-template.json`, `.devcontainer.json`,
and `docker-compose.yaml` (plus `README.md`, and a `Dockerfile` for VSCode) — that drops into
`workbench-app-devcontainers/src/<app-name>/` and runs as a Workbench custom app with the
requested packages pre-installed via the `common-packages` feature.

---

## Why a whole folder, not one file (READ FIRST)

A Workbench app is a **folder**, not a single standalone `.devcontainer.json`. Workbench's
custom-app flow needs the whole folder: the `docker-compose.yaml` defines the
`application-server` container that actually runs the app (image, port, `app-network`, fuse
mounts), and the startup scripts wire up bucket mounting. A lone `.devcontainer.json` will **not**
launch the app.

So the output is a folder the customer commits under `src/<app-name>/` and points their custom
app config at.

---

## App type → base template → specifics

Base each new app on the **existing template** for its type. Read that template's real files from
`src/<app>/` and copy them (don't hand-copy from memory — this keeps pinned feature digests and
startup wiring current), then inject `common-packages`.

| App type | Base template | image | port | user | home | extra file |
|----------|--------------|-------|------|------|------|-----------|
| **Jupyter / JupyterLab** (default) | `src/custom-workbench-jupyter-template/` | **prebuilt** `app-workbench-jupyter` (via `Dockerfile`) | 8888 | jupyter | /home/jupyter | `Dockerfile` |
| **RStudio / R / R Shiny** | `src/r-analysis/` | `ghcr.io/rocker-org/devcontainer/tidyverse` | 8787 | rstudio | /home/rstudio | — |
| **VSCode** | `src/vscode/` | `lscr.io/linuxserver/code-server` (via `Dockerfile`) | 8443 | abc | /config | `Dockerfile` |

> ⚠️ **Do NOT base Jupyter apps on `src/jupyter-template/`** — it defaults to a bare `debian:bullseye`
> image and tries to build Python/JupyterLab from scratch, which fails at deploy
> (`sysconfig.get_default_scheme` / `post-startup.sh` errors). Always use the **prebuilt-image**
> template `src/custom-workbench-jupyter-template/` (it has a `Dockerfile` + `docker-compose.yaml`
> that `include`s `../jupyter-common/jupyter-common-compose.yaml`). Jupyter folders therefore have
> **four** files: `.devcontainer.json`, `docker-compose.yaml`, `devcontainer-template.json`,
> `Dockerfile` (copy the `Dockerfile` from `src/custom-workbench-jupyter-template/`).

---

## Package mechanism

- **Python packages** → `common-packages` `pythonPackages` (space-separated).
- **R / R Shiny packages** → `common-packages` `rPackages` (comma-separated, no spaces). Note
  `src/r-analysis` already installs `shiny,shinydashboard` via the rocker `r-packages` feature;
  the user's extra R packages go through `common-packages`.
- **VSCode extensions** are **not** pip/R packages — they're installed in the app's `Dockerfile`
  from open-vsx. `common-packages` only covers Python/R libraries usable in the terminal. If a
  VSCode user's "packages" are ambiguous, ask which they mean.

Add this block to the template's `features` in `.devcontainer.json` (include only the key(s)
requested):

```json
"ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
  "pythonPackages": "pandas numpy scikit-learn",
  "rPackages": "tidyverse,ggplot2"
}
```

---

## Output Contract

- **Emit the whole folder in one response.** One fenced code block per file, each labeled with
  its path: `src/<app-name>/.devcontainer.json`, `src/<app-name>/docker-compose.yaml`,
  `src/<app-name>/devcontainer-template.json`, `src/<app-name>/README.md` (+ `Dockerfile` for
  VSCode).
- **Complete files**, copy-pasteable, valid JSON/YAML. Keep `container_name: "application-server"`,
  `networks: app-network` with `external: true`, fuse mounts, and the startupscript hooks intact.
- **Pick an app name** from the request (e.g. `custom-jupyter-ml`); tell the user they can rename
  the folder.
- **One-line placement note:** *"Drop this folder into `workbench-app-devcontainers/src/<app-name>/`,
  push it, and point your custom app config at that folder."*
- **No follow-up questions** once app type and packages are known. Only exceptions: ambiguous
  domain language (Python `scanpy` vs R `Seurat`), or VSCode "packages" (extensions vs libraries).

For mapping vague domains ("machine learning", "genomics") to concrete package lists, see
`INSTALL_PACKAGES.md`.

---

## Worked example: JupyterLab with pandas, numpy, scikit-learn

**User:** "Create a JupyterLab app with pandas, numpy, and scikit-learn"

Emit the folder `src/custom-jupyter-ml/`, based on **`src/custom-workbench-jupyter-template/`** (the
prebuilt-image template) + `common-packages`. Four files:

`src/custom-jupyter-ml/.devcontainer.json`:
```json
{
  "name": "custom-jupyter-ml",
  "dockerComposeFile": ["docker-compose.yaml", "../jupyter-common/jupyter-common-compose.yaml"],
  "service": "app",
  "runServices": ["app"],
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "postCreateCommand": [
    "./startupscript/post-startup.sh",
    "jupyter",
    "/home/jupyter",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "postStartCommand": [
    "./startupscript/remount-on-restart.sh",
    "jupyter",
    "/home/jupyter",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "features": {
    "./.devcontainer/features/workbench-tools": {
      "libEnv": "/opt/conda/envs/jupyter",
      "cloud": "${templateOption:cloud}",
      "username": "jupyter",
      "userHomeDir": "/home/jupyter"
    },
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas numpy scikit-learn"
    }
  },
  "remoteUser": "root",
  "customizations": {
    "workbench": {
      "opens": {
        "extensions": [
          ".ipynb", ".R", ".py",
          ".md", ".html", ".latex", ".pdf",
          ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg",
          ".csv", ".tsv", ".json", ".vl"
        ],
        "fileUrlSuffix": "/lab/tree/{path}",
        "folderUrlSuffix": "/lab/tree/{path}"
      }
    }
  }
}
```

`src/custom-jupyter-ml/docker-compose.yaml`:
```yaml
include:
  - ../jupyter-common/jupyter-common-compose.yaml
services:
  app:
    container_name: "application-server"
    build:
      context: .
      additional_contexts:
        jupyter-extension-builder: service:jupyter-common-extension-builder
    user: "jupyter"
    restart: always
    volumes:
      - .:/workspace:cached
    ports:
      - "8888:8888"
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
```

`src/custom-jupyter-ml/Dockerfile` (copy verbatim from `src/custom-workbench-jupyter-template/Dockerfile`):
```dockerfile
FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:325ce4e4228c93e393872055dac2d3de067b179cf0921fc60fc41ce325b1e2f9

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh
```

`src/custom-jupyter-ml/devcontainer-template.json`:
```json
{
  "id": "custom-jupyter-ml",
  "version": "1.0.0",
  "name": "custom-jupyter-ml",
  "description": "Custom JupyterLab app with pre-installed packages: pandas numpy scikit-learn",
  "documentationURL": "https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/custom-jupyter-ml",
  "licenseURL": "https://github.com/verily-src/workbench-app-devcontainers/blob/master/LICENSE",
  "options": {
    "cloud": {
      "type": "string",
      "description": "VM cloud environment",
      "proposals": ["gcp", "aws"],
      "default": "gcp"
    },
    "login": {
      "type": "string",
      "description": "Whether to log in to workbench CLI",
      "proposals": ["true", "false"],
      "default": "false"
    }
  },
  "platforms": ["Any"]
}
```

`src/custom-jupyter-ml/README.md`:
```markdown
# custom-jupyter-ml

Custom Workbench JupyterLab app with pre-installed packages (prebuilt `app-workbench-jupyter` base).

- **Python packages:** pandas, numpy, scikit-learn (installed via the `common-packages` feature)
- **Port:** 8888

## Usage

1. Commit this folder under `src/custom-jupyter-ml/` in your fork of
   `workbench-app-devcontainers` and push.
2. In the Workbench UI, create a custom app pointing at your repo, and set the folder to
   `src/custom-jupyter-ml`.
```

**Lead-in to give the user:** *"Drop this folder into
`workbench-app-devcontainers/src/custom-jupyter-ml/`, push it, and point your custom app config at
that folder. Rename the folder if you like."*

---

## RStudio / R Shiny

Same shape, based on `src/r-analysis/`. Keep its `features` (java, rocker `r-packages` with
`shiny,shinydashboard`, aws-cli, google-cloud-cli, node, claude-code, gemini-cli, workbench-tools,
postgres-client) and add `common-packages` with the user's R packages:

```json
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "rPackages": "tidyverse,DESeq2"
    }
```

Its `docker-compose.yaml` uses `image: ghcr.io/rocker-org/devcontainer/tidyverse@...`, port 8787,
`DISABLE_AUTH=true`, and a `work` volume for `/home/rstudio`. `devcontainer-template.json` uses the
standard `cloud`/`login` options (no `containerImage`/`containerPort`). R Shiny is already
included — the user's extra R packages come through `common-packages`.

---

## VSCode

Based on `src/vscode/`. This app builds from a `Dockerfile` (`lscr.io/linuxserver/code-server`),
so the folder includes **four** files: `.devcontainer.json`, `docker-compose.yaml`,
`devcontainer-template.json`, and `Dockerfile` (copy `src/vscode/Dockerfile`). Port 8443, user
`abc`, home `/config`. Add `common-packages` for terminal Python/R libraries:

```json
    "ghcr.io/verily-src/workbench-app-devcontainers/common-packages": {
      "pythonPackages": "pandas scikit-learn"
    }
```

Reminder: VSCode **editor extensions** are installed in the `Dockerfile` from open-vsx, not via
`common-packages`. If the user asked for extensions, edit the `Dockerfile` instead.

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
