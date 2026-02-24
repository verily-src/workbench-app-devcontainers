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

All templates are in:
```
https://github.com/aculotti-verily/wb-app-mcp-and-context/tree/templates-only/src/templates/
```

Each template contains:
- `manifest.yaml` - Capabilities and inputs
- `.devcontainer.json` - Devcontainer config
- `docker-compose.yaml` - Container setup
- `Dockerfile` - Build instructions
- `app/` - Application code
- `README.md` - Documentation

---

## How to Use a Template

### Option 1: Deploy Directly
```
Repository: https://github.com/aculotti-verily/wb-app-mcp-and-context.git
Branch: templates-only
Folder: src/templates/<template-name>
```

### Option 2: Copy and Customize
1. Copy the template folder to user's repo
2. Modify application code in `app/`
3. Update `devcontainer-template.json` with new name/description
4. Push to GitHub
5. Deploy from user's repo

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

- [ ] Container name is `application-server`
- [ ] Network is `app-network` with `external: true`
- [ ] Port is exposed and mapped correctly
- [ ] `devcontainer-template.json` has unique `id`
- [ ] Application binds to `0.0.0.0` (not `localhost`)

---

## Summary

| Need | Template | Customization Effort |
|------|----------|---------------------|
| Quick API | flask-api | Low - add endpoints |
| Data dashboard | streamlit-dashboard | Low - add tabs |
| R analysis | rshiny-dashboard | Low - modify app.R |
| File processing | file-processor | Low - add processors |
| Something else | CUSTOM_APP.md | Medium - from scratch |
