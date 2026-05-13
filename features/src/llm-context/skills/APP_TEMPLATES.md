# App Templates for Workbench

**Pre-built, ready-to-deploy application templates with workspace resource integration.**

> **When to use this:** User wants an app that visualizes data, serves an API, processes files, or creates dashboards using their workspace resources.

---

## Available Templates

| Template | Best For | Port | Key Features |
|----------|----------|------|--------------|
| **flask-api** | REST APIs, backend services, data processing | 8080 | JSON endpoints, file upload, BQ queries |
| **streamlit-dashboard** | Data visualization, interactive exploration | 8501 | Charts, file browser, BigQuery explorer |
| **rshiny-dashboard** | R statistical analysis, R-based visualizations | 3838 | Shiny UI, plotly, ggplot2, tidyverse |
| **file-processor** | File upload, validation, transformation | 8080 | Drag-drop UI, auto-save to GCS, schema validation |

---

## Template Selection Guide

### Ask the user these questions:

1. **What language/framework preference?**
   - Python → `flask-api`, `streamlit-dashboard`, `file-processor`
   - R → `rshiny-dashboard`

2. **What's the primary purpose?**
   - API/Backend service → `flask-api`
   - Interactive dashboard → `streamlit-dashboard` or `rshiny-dashboard`
   - Process/upload files → `file-processor`

3. **What workspace resources do they need?**
   - All templates support GCS buckets and BigQuery

### Quick Decision Matrix

| User Says... | Recommend |
|--------------|-----------|
| "dashboard", "visualize", "charts", "explore data" | `streamlit-dashboard` |
| "API", "endpoint", "backend", "REST", "service" | `flask-api` |
| "R", "statistical", "ggplot", "tidyverse" | `rshiny-dashboard` |
| "upload", "process files", "validate", "CSV" | `file-processor` |
| "something custom", "from scratch" | → Use `CUSTOM_APP.md` skill |

---

## Template Locations

The official app repository contains reference implementations and examples:
```
https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/
```

Good starting points:
- [`example`](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/example) — Minimal standalone app (ttyd terminal)
- [`workbench-vscode`](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/workbench-vscode) — Full-featured VS Code Server

Each app contains:
- `.devcontainer.json` - Devcontainer config
- `docker-compose.yaml` - Container setup
- `Dockerfile` - Build instructions
- `devcontainer-template.json` - Template metadata
- Application code

---

## How to Use a Template

### Recommended: Fork and Customize

The official repo (`verily-src/workbench-app-devcontainers`) is a curated collection of common/default apps. **Create a fork** for your custom app rather than submitting a PR to the org repo:

1. Fork https://github.com/verily-src/workbench-app-devcontainers
2. Copy an existing app folder (e.g., `src/example`) to `src/my-app`
3. Modify application code
4. Update `devcontainer-template.json` with new name/description
5. Push to your fork
6. Deploy from your fork's repo URL

### Alternative: Standalone Repo
1. Copy the template files to a new repository
2. Ensure `.devcontainer.json` is at the repo root
3. Push to GitHub and deploy from your repo

> ⚠️ Volume mounts (`volumes: .:/workspace`) are for local dev only. In production, Workbench builds the image — code must be baked in via `COPY` in the Dockerfile. Do not rely on volume mounts for deployed apps.

---

## Template Details

### 1. Flask API (`flask-api`)

**Capabilities:** REST API, JSON, file upload, BigQuery, GCS

**Pre-built endpoints:**
- `GET /health` - Health check
- `GET /resources` - List workspace resources
- `GET /buckets/<name>/files` - List bucket files
- `POST /buckets/<name>/upload` - Upload to bucket
- `POST /bigquery/query` - Run BQ query
- `GET /bigquery/tables/<dataset>` - List tables
- `POST /process` - Custom processing (user extends this)

**Customization points:**
- Add endpoints in `app/main.py`
- Add dependencies in `app/requirements.txt`

---

### 2. Streamlit Dashboard (`streamlit-dashboard`)

**Capabilities:** Interactive UI, charts, data exploration, BigQuery, GCS

**Pre-built features:**
- GCS file browser with CSV preview
- BigQuery query interface
- Data visualization (line, bar, scatter)
- Workspace resource sidebar

**Customization points:**
- Add tabs/pages in `app/main.py`
- Add visualizations with plotly/altair
- Add additional data sources

---

### 3. RShiny Dashboard (`rshiny-dashboard`)

**Capabilities:** R analysis, Shiny UI, plotly, statistical visualization

**Pre-built features:**
- Dashboard layout with shinydashboard
- Data upload and exploration
- Interactive charts with plotly
- Workspace resource viewer

**R packages included:**
- shiny, shinydashboard, DT
- plotly, ggplot2
- dplyr, tidyr
- bigrquery, googleCloudStorageR

**Customization points:**
- Modify UI in `app/app.R`
- Add R packages in Dockerfile
- Add statistical analysis functions

---

### 4. File Processor (`file-processor`)

**Capabilities:** File upload, validation, transformation, GCS storage

**Pre-built features:**
- Drag-and-drop upload UI
- CSV, JSON, Excel processing
- Auto-save to GCS bucket
- Schema validation endpoint

**Supported formats:**
- CSV → Row/column analysis, schema detection
- JSON → Structure analysis, schema validation
- Excel → Sheet parsing, data extraction

**Customization points:**
- Add processing logic in `app/main.py`
- Add validation schemas
- Add transformation pipelines

---

## Workspace Resource Integration

All templates automatically detect workspace resources:

### Python Templates
```python
import os

# All resources as dict
resources = {
    k.replace("WORKBENCH_", ""): v 
    for k, v in os.environ.items() 
    if k.startswith("WORKBENCH_")
}

# Specific resource
bucket = os.environ.get("WORKBENCH_my_bucket")
```

### R Template
```r
# All resources
resources <- Sys.getenv()
wb_vars <- resources[grepl("^WORKBENCH_", names(resources))]

# Specific resource
bucket <- Sys.getenv("WORKBENCH_my_bucket")
```

---

## When Templates Don't Fit

If the user's requirements don't match any template:

1. **Check if a template can be extended**
   - Most templates are customizable
   - Adding endpoints to flask-api is easy
   - Adding tabs to streamlit is easy

2. **If truly custom, use CUSTOM_APP.md skill**
   - Minimal from-scratch pattern
   - Avoid common pitfalls
   - Full control over everything

---

## Common Customizations

### Add a new endpoint (Flask)
```python
# app.config['STRICT_SLASHES'] = False should already be set in the template — do not remove it
@app.route("/my-endpoint", methods=["POST"])
def my_endpoint():
    data = request.get_json()
    # Your logic here
    return jsonify({"result": "success"})
```

### Add a new tab (Streamlit)
```python
tab1, tab2, tab3, tab4 = st.tabs(["Existing", "Tabs", "Here", "New Tab"])

with tab4:
    st.header("My New Feature")
    # Your code here
```

### Add R packages (RShiny)
```dockerfile
# In Dockerfile, add to install.packages():
RUN R -e "install.packages(c('existingpkgs', 'newpackage'))"
```

---

## Deployment Checklist

Before deploying any template:

- [ ] `.devcontainer.json` at repo ROOT (not in a subfolder)
- [ ] Container name is `application-server`
- [ ] Network is `app-network` with `external: true`
- [ ] Port is exposed and mapped correctly
- [ ] `devcontainer-template.json` has unique `id`
- [ ] Application binds to `0.0.0.0` (not `localhost`)
- [ ] All `fetch()` calls use relative paths — `fetch('api/data')` ✅ not `fetch('/api/data')` ❌
- [ ] All `<a href>` and `<link>` use relative paths — leading `/` routes to `workbench.verily.com`, causing 404s
- [ ] Do not use `url_for()` for frontend-facing links — generates wrong paths behind the proxy

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| App fails to create | `.devcontainer.json` not at repo root | Move to repo root |
| 308 redirect loop | Flask missing `STRICT_SLASHES` setting | Add `app.config['STRICT_SLASHES'] = False` |
| 404 on API calls | Leading `/` in `fetch()` path | Use `fetch('api/data')` not `fetch('/api/data')` |
| Build fails on pip install | Unpinned dependencies | Pin versions in `requirements.txt` |
| App works locally but not deployed | Volume mount used instead of `COPY` | Bake code into image via Dockerfile `COPY` |
| Container restart loop | App crashes on startup | Check `docker logs application-server` |

---

## Summary

| Need | Template | Customization Effort |
|------|----------|---------------------|
| Quick API | flask-api | Low - add endpoints |
| Data dashboard | streamlit-dashboard | Low - add tabs |
| R analysis | rshiny-dashboard | Low - modify app.R |
| File processing | file-processor | Low - add processors |
| Something else | CUSTOM_APP.md | Medium - from scratch |
