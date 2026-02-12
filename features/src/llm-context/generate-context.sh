#!/bin/bash
#
# Workbench LLM Context Generator
# 
# This script generates a single CLAUDE.md file that provides LLMs (like 
# Claude Code) with full context about the current Workbench workspace,
# resources, workflows, and available tools. The file includes embedded
# JSON for machine-readable data.
#
# Usage: ./generate-context.sh
#
# Prerequisites:
#   - Workbench CLI (wb) installed and authenticated
#   - jq installed for JSON processing
#   - Active workspace set (wb workspace set <workspace-id>)
#
# CLI JSON Field Reference:
#   Workspace (UFWorkspaceLight.java):
#     - id: user-facing ID (e.g., "my-workspace")
#     - uuid: UUID
#     - name: display name
#     - description
#     - cloudPlatform: GCP or AWS
#     - googleProjectId, awsAccountId
#     - highestRole: OWNER, WRITER, READER
#     - orgId, podId
#     - userEmail
#     - createdDate, lastUpdatedDate
#     - properties: Map<String, String>
#
#   Resource (UFResource.java):
#     - id: resource name
#     - uuid
#     - description
#     - resourceType: GCS_BUCKET, BQ_DATASET, GIT_REPO, etc.
#     - stewardshipType: CONTROLLED, REFERENCED
#     - region
#     - For GCS: bucketName, location
#     - For BQ: projectId, datasetId
#
#   Workflow (UFWorkflow.java):
#     - id: name
#     - workflowId: UUID
#     - displayName
#     - description
#     - bucketSource or gitSource
#

set -e

# Configuration
CONTEXT_DIR="${HOME}/.workbench"
SKILLS_DIR="${CONTEXT_DIR}/skills"
CLAUDE_FILE="${CONTEXT_DIR}/CLAUDE.md"
# Visible symlink in home directory for Claude Code auto-discovery
VISIBLE_CLAUDE_SYMLINK="${HOME}/CLAUDE.md"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v wb &> /dev/null; then
        log_error "Workbench CLI (wb) not found. Please install it first."
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        log_error "jq is required but not found. Please install jq."
        exit 1
    fi
    
    # Check if workspace is set
    if ! wb workspace describe --format=json &> /dev/null; then
        log_error "No workspace set or not authenticated. Please run:"
        log_error "  wb auth login --mode=APP_DEFAULT_CREDENTIALS"
        log_error "  wb workspace set <workspace-id>"
        log_error ""
        log_error "Note: Use --mode=APP_DEFAULT_CREDENTIALS inside Workbench apps"
        exit 1
    fi
    
    log_info "Prerequisites OK"
}

# Create output directory
setup_directories() {
    log_info "Setting up directories..."
    mkdir -p "${CONTEXT_DIR}"
    mkdir -p "${SKILLS_DIR}"
}

# Install skill files (embedded - no network needed)
install_skills() {
    log_info "Installing skill files..."
    
    # Create CUSTOM_APP.md skill (full version, embedded)
    log_info "Creating CUSTOM_APP.md skill..."
    cat > "${SKILLS_DIR}/CUSTOM_APP.md" << 'SKILL_EOF'
# Creating Custom Workbench Apps

**Practical guide for creating simple, reliable Workbench apps.**

> **When to use this guide:** For simple apps (Flask APIs, static sites, custom tools).
> For apps needing Workbench CLI, gcloud, or Jupyter, see the [full-featured approach](https://github.com/verily-src/workbench-app-devcontainers).

## TL;DR - The Minimal Pattern That Works

Workbench custom apps need exactly **three things**:
1. Container named `application-server`
2. Connected to `app-network` (external Docker network)
3. HTTP server on a port

**That's it.** Everything else is optional (and often causes problems).

---

## The Minimal Working Pattern (Copy This)

### File 1: `.devcontainer.json`
```json
{
  "name": "Your App Name",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "remoteUser": "root"
}
```

### File 2: `docker-compose.yaml`
```yaml
services:
  app:
    container_name: "application-server"
    build:
      context: ../..
      dockerfile: src/YOUR-APP-NAME/Dockerfile
    restart: always
    ports:
      - "8080:8080"
    networks:
      - app-network

networks:
  app-network:
    external: true
```

### File 3: `Dockerfile`
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY src/YOUR-APP-NAME/app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/YOUR-APP-NAME/app/ .

EXPOSE 8080

CMD ["python", "your_app.py"]
```

### File 4: `devcontainer-template.json`
```json
{
  "id": "your-app-name",
  "description": "Your app description",
  "version": "1.0.0",
  "name": "Your App Name",
  "options": {},
  "platforms": ["Any"]
}
```

---

## Directory Structure

```
src/YOUR-APP-NAME/
├── .devcontainer.json
├── devcontainer-template.json
├── docker-compose.yaml
├── Dockerfile
├── README.md
└── app/
    ├── your_app.py
    ├── requirements.txt
    └── (other files)
```

---

## What NOT To Do (Lessons Learned)

### DON'T use complex base images unless needed
❌ `workbench-jupyter` base image - Has its own startup config that conflicts with CMD overrides
✅ `python:3.11-slim` - Clean, simple, no surprises

### DON'T use devcontainer features
❌ Features like `ghcr.io/dhoeric/features/google-cloud-cli` - Uses deprecated `apt-key`, fails on newer Debian
❌ Features like `workbench-tools` - Expect specific system packages
✅ Install what you need directly in the Dockerfile

### DON'T use postCreateCommand/postStartCommand
❌ `./startupscript/post-startup.sh` - Expects specific user/home structure, may fail
✅ Self-contained Dockerfile with everything built in

### DON'T use supervisor for multiple processes (unless truly needed)
❌ Supervisor + Jupyter + Flask - Complex, many failure points
✅ Single process serving everything (Flask can serve static files)

### DON'T fight with Jupyter config
❌ Overriding CMD on workbench-jupyter image - Causes `root_dir`/`file_to_run` conflicts
✅ Don't use Jupyter at all if you don't need it

---

## Flask App: Serve Static Files Directly

If your app has a Flask backend + static HTML, just have Flask serve everything:

```python
import os
from flask import Flask
from flask_cors import CORS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=SCRIPT_DIR, static_url_path='/static')
CORS(app)

@app.route('/')
def serve_index():
    return app.send_static_file('index.html')

# ... your other routes ...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

**No separate HTTP server needed. No supervisor. One process.**

---

## Common Errors and Fixes

### Error: `apt-key: command not found`
**Cause:** Devcontainer feature uses deprecated apt-key on newer Debian
**Fix:** Remove the feature from .devcontainer.json, install directly in Dockerfile if needed

### Error: `root_dir and file_to_run are incompatible`
**Cause:** Overriding CMD on workbench-jupyter base image conflicts with its config
**Fix:** Don't use workbench-jupyter. Use python:3.11-slim instead

### Error: `supports_credentials in conjunction with origin '*'`
**Cause:** Flask-CORS config conflict
**Fix:** Just use `CORS(app)` with no options

### Error: Container restart loop
**Cause:** Main process exits immediately
**Fix:** Make sure your CMD runs a long-lived process (Flask server, not a script that exits)

### Error: `Application-server port is empty`
**Cause:** Container not exposing port correctly, or app crashing before binding
**Fix:** Check `docker logs application-server` to see the actual error

---

## Deployment

### Deploy to Workbench
In Workbench UI, create custom app with:
- **Repository:** `git@github.com:YOUR-ORG/YOUR-REPO.git`
- **Branch:** `your-branch`
- **Folder:** `src/YOUR-APP-NAME`

### For faster deploys (optional): Push to GAR
```bash
# Build
cd src/YOUR-APP-NAME
docker compose build

# Tag
export TAG="us-central1-docker.pkg.dev/PROJECT/REPO/NAME:$(date +'%Y%m%d')"
docker tag YOUR-APP-NAME-app:latest ${TAG}

# Push
docker push ${TAG}

# Update docker-compose.yaml to use image: instead of build:
```

---

## Local Testing

```bash
# Create required network
docker network create app-network

# Build and run
cd src/YOUR-APP-NAME
docker compose build
docker compose up

# Access at http://localhost:8080
```

---

## Debugging on VM

```bash
# SSH to VM, then:
docker logs application-server --tail 100
docker exec -it application-server /bin/sh
docker ps -a
```

---

## Reference Implementations

All examples are in the public repo: https://github.com/verily-src/workbench-app-devcontainers

| App | Description | Complexity |
|-----|-------------|------------|
| `src/playground/` | Multi-service app with Caddy | Simple |
| `src/vscode/` | VS Code Server on port 8443 | Pre-built image |
| `src/r-analysis/` | RStudio on port 8787 | Pre-built image |
| `src/workbench-jupyter/` | JupyterLab with Workbench tools | Full-featured |

---

## When DO You Need Features?

Sometimes you genuinely need the full-featured approach:

| Need | Solution |
|------|----------|
| Workbench CLI (`wb`) | Use `workbench-tools` feature |
| LLM/MCP integration | Use `wb-mcp-server` feature |
| Pre-authenticated gcloud | Use `workbench-tools` feature |
| Jupyter notebooks | Use `workbench-jupyter` base image |

**If you need these, accept the complexity.** But test thoroughly.

---

## Key Insight

The old guides suggested using `workbench-jupyter` base image + devcontainer features + startup scripts. This adds complexity that causes failures.

The **playground pattern** proves you only need:
1. A container named `application-server`
2. On the `app-network` network
3. Serving HTTP on a port

Everything else is optional convenience that often breaks.

**When in doubt, simplify.**
SKILL_EOF

    # Create APP_TEMPLATES.md skill (full version, embedded)
    log_info "Creating APP_TEMPLATES.md skill..."
    cat > "${SKILLS_DIR}/APP_TEMPLATES.md" << 'TEMPLATES_SKILL_EOF'
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

### Quick Decision Matrix

| User Says... | Recommend |
|--------------|-----------|
| "dashboard", "visualize", "charts", "explore data" | `streamlit-dashboard` |
| "API", "endpoint", "backend", "REST", "service" | `flask-api` |
| "R", "statistical", "ggplot", "tidyverse" | `rshiny-dashboard` |
| "upload", "process files", "validate", "CSV" | `file-processor` |
| "something custom", "from scratch" | → Use `CUSTOM_APP.md` skill |

---

## Template Location

All templates are at:
```
https://github.com/aculotti-verily/wb-app-mcp-and-context/tree/templates-only/src/templates/
```

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
4. Push to GitHub and deploy

---

## Template Summaries

### flask-api (Port 8080)
- REST API with Flask
- Pre-built endpoints: `/health`, `/resources`, `/buckets/<name>/files`, `/bigquery/query`
- Easy to add custom endpoints

### streamlit-dashboard (Port 8501)
- Interactive dashboard with tabs
- GCS file browser, BigQuery explorer, visualization
- Easy to add new tabs/charts

### rshiny-dashboard (Port 3838)
- R-based Shiny dashboard
- Includes: shiny, shinydashboard, plotly, ggplot2, dplyr, tidyr
- bigrquery and googleCloudStorageR for data access

### file-processor (Port 8080)
- Drag-drop file upload UI
- Processes CSV, JSON, Excel
- Auto-save to GCS buckets
- Schema validation

---

## Workspace Resource Integration

All templates auto-detect workspace resources via environment variables:

```python
# Python
import os
bucket = os.environ.get("WORKBENCH_my_bucket")
```

```r
# R
bucket <- Sys.getenv("WORKBENCH_my_bucket")
```

---

## When Templates Don't Fit

If no template matches:
1. Check if a template can be extended (usually yes)
2. If truly custom, read `~/.workbench/skills/CUSTOM_APP.md`
TEMPLATES_SKILL_EOF
}

# Fetch workspace information
fetch_workspace() {
    log_info "Fetching workspace information..."
    wb workspace describe --format=json 2>/dev/null || echo "{}"
}

# Fetch resources
fetch_resources() {
    log_info "Fetching resources..."
    wb resource list --format=json 2>/dev/null || echo "[]"
}

# Fetch workflows (may not exist in all workspaces)
fetch_workflows() {
    log_info "Fetching workflows..."
    wb workflow list --format=json 2>/dev/null || echo "[]"
}

# Fetch apps
fetch_apps() {
    log_info "Fetching apps..."
    wb app list --format=json 2>/dev/null || echo "[]"
}

# Generate embedded JSON (returns JSON to stdout, doesn't write to file)
generate_embedded_json() {
    local resources="$1"
    
    # Generate resourcePaths map: resource name -> cloud path
    local resource_paths=$(echo "$resources" | jq -c '
        map(
            {
                key: .id,
                value: (
                    if .resourceType == "GCS_BUCKET" then "gs://\(.bucketName)"
                    elif .resourceType == "BQ_DATASET" then "\(.projectId).\(.datasetId)"
                    elif .resourceType == "BQ_TABLE" then "\(.projectId).\(.datasetId).\(.tableId // "")"
                    elif .resourceType == "GIT_REPO" then .gitRepoUrl
                    elif .resourceType == "GCS_OBJECT" then "gs://\(.bucketName)/\(.objectName // "")"
                    else null
                    end
                )
            }
        ) | map(select(.value != null)) | from_entries
    ')
    
    # Generate envVars map: WORKBENCH_<name> -> cloud path
    local env_vars=$(echo "$resources" | jq -c '
        map(
            {
                key: ("WORKBENCH_" + (.id | gsub("-"; "_"))),
                value: (
                    if .resourceType == "GCS_BUCKET" then "gs://\(.bucketName)"
                    elif .resourceType == "BQ_DATASET" then "\(.projectId).\(.datasetId)"
                    elif .resourceType == "BQ_TABLE" then "\(.projectId).\(.datasetId).\(.tableId // "")"
                    elif .resourceType == "GIT_REPO" then .gitRepoUrl
                    elif .resourceType == "GCS_OBJECT" then "gs://\(.bucketName)/\(.objectName // "")"
                    else null
                    end
                )
            }
        ) | map(select(.value != null)) | from_entries
    ')
    
    # Output compact JSON for embedding
    jq -n \
        --argjson resource_paths "$resource_paths" \
        --argjson env_vars "$env_vars" \
        '{
          "resourcePaths": $resource_paths,
          "envVars": $env_vars
        }'
}

# Generate bucket list for data persistence section
generate_bucket_list() {
    local resources="$1"
    
    # Filter to only GCS_BUCKET resources
    local buckets=$(echo "$resources" | jq '[.[] | select(.resourceType == "GCS_BUCKET")]' 2>/dev/null || echo "[]")
    local count=$(echo "$buckets" | jq 'length' 2>/dev/null || echo "0")
    
    if [ "$count" -eq 0 ] || [ "$count" = "0" ]; then
        echo "*No GCS buckets in this workspace.* Create one with:"
        echo '```bash'
        echo 'wb resource create gcs-bucket --name my-storage --description "Storage for results"'
        echo '```'
        return
    fi
    
    echo "| Bucket Name | Resource ID | Description |"
    echo "|-------------|-------------|-------------|"
    
    echo "$buckets" | jq -r '.[] | "| `gs://\(.bucketName // "unknown")/` | `\(.id // "—")` | \(.description // "—" | if . == "" then "—" else . end) |"' 2>/dev/null || true
}

# Generate CLAUDE.md
generate_claude_md() {
    log_info "Generating CLAUDE.md..."
    
    local workspace="$1"
    local resources="$2"
    local workflows="$3"
    local apps="$4"
    
    # Extract workspace values - field names match UFWorkspaceLight.java
    local ws_name=$(echo "$workspace" | jq -r '.name // "Unnamed Workspace"')
    local ws_id=$(echo "$workspace" | jq -r '.id // "unknown"')
    local ws_desc=$(echo "$workspace" | jq -r '.description // "No description"')
    local ws_cloud=$(echo "$workspace" | jq -r '.cloudPlatform // "GCP"')
    local ws_gcp_project=$(echo "$workspace" | jq -r '.googleProjectId // ""')
    local ws_aws_account=$(echo "$workspace" | jq -r '.awsAccountId // ""')
    local ws_role=$(echo "$workspace" | jq -r '.highestRole // "READER"')
    local ws_user=$(echo "$workspace" | jq -r '.userEmail // "unknown"')
    local ws_org=$(echo "$workspace" | jq -r '.orgId // ""')
    local ws_server=$(echo "$workspace" | jq -r '.serverName // ""')
    
    # Determine project display
    local project_display="$ws_gcp_project"
    if [ -n "$ws_aws_account" ] && [ "$ws_aws_account" != "null" ] && [ "$ws_aws_account" != "" ]; then
        project_display="$ws_aws_account"
    fi
    
    # Generate dynamic sections
    local embedded_json=$(generate_embedded_json "$resources")
    local bucket_list=$(generate_bucket_list "$resources")
    
    # Write the file
    cat > "${CLAUDE_FILE}" << EOF
# Workbench Context

You are working inside **Verily Workbench**, a secure cloud-based research environment for biomedical data analysis.

---

## What is Verily Workbench?

Verily Workbench is a platform that enables researchers to:
- Access and analyze biomedical data (clinical, genomics, wearables, imaging)
- Run computational workflows at scale (WDL, Nextflow)
- Collaborate securely with governance and policy enforcement
- Use familiar tools (Jupyter, RStudio, VS Code) in the cloud

---

## Current Workspace

| Property | Value |
|----------|-------|
| **Name** | ${ws_name} |
| **ID** | \`${ws_id}\` |
| **Cloud Platform** | ${ws_cloud} |
| **Project/Account** | \`${project_display}\` |
| **Your Role** | ${ws_role} |
| **User** | ${ws_user} |
| **Organization** | ${ws_org:-"—"} |
| **Server** | ${ws_server:-"—"} |

### Description
${ws_desc}

---

## Key Concepts

### Workspaces
A **workspace** is a secure container for your research project. It contains:
- **Resources**: Cloud assets like buckets, datasets, repos
- **Workflows**: Reproducible analysis pipelines
- **Apps**: Interactive compute environments (this app!)
- **Policies**: Access controls and constraints

### Resources
Resources are cloud assets managed by Workbench:

| Type | Description | CLI Create Command |
|------|-------------|-------------------|
| \`GCS_BUCKET\` | Google Cloud Storage bucket | \`wb resource create gcs-bucket\` |
| \`BQ_DATASET\` | BigQuery dataset | \`wb resource create bq-dataset\` |
| \`GIT_REPO\` | Git repository reference | \`wb resource add-ref git-repo\` |
| \`GCS_OBJECT\` | Individual GCS file reference | \`wb resource add-ref gcs-object\` |
| \`BQ_TABLE\` | BigQuery table reference | \`wb resource add-ref bq-table\` |

**Environment Variables**: Each resource is available as \`\$WORKBENCH_<resource_name>\` (e.g., \`\$WORKBENCH_my_bucket\`).

### Data Collections
Data collections are curated datasets in the Workbench catalog. When added to a workspace, their resources are cloned into **folders**.

#### Identifying Resources from Data Collections

Use the **MCP server** to find which data collection a resource came from:

1. **Use the MCP \`get_resource\` tool** to get full resource metadata including lineage
2. The \`resourceLineage\` array contains:
   - \`sourceWorkspaceId\`: UUID of the data collection
   - \`sourceResourceId\`: UUID of the original resource

**Example:** Ask "Use get_resource to get lineage for resource 'clinical-bq-dataset'"

The response includes:
\`\`\`json
{
  "resourceLineage": [
    { "sourceWorkspaceId": "abc123-...", "sourceResourceId": "def456-..." }
  ]
}
\`\`\`

### Workflows
Workflows are reproducible pipelines in WDL or Nextflow format, registered in the workspace.

---

## ⚠️ Important: Data Persistence

> **LOCAL STORAGE IS EPHEMERAL.** Files saved on this app's local disk will be **lost** when the app stops or restarts.

### The Problem
Users often create files locally (notebooks, scripts, outputs) without realizing they won't persist. When the app shuts down, all local work is lost.

### The Solution
**Save important files to a cloud bucket** in your workspace. Buckets persist independently of apps.

### Available Storage Buckets in This Workspace

${bucket_list}

### How to Save Local Files to Cloud Storage

\`\`\`bash
# Copy a single file to a bucket
gsutil cp my-notebook.ipynb gs://<bucket-name>/notebooks/

# Copy a directory recursively
gsutil -m cp -r ./my-results/ gs://<bucket-name>/results/

# Sync a local directory (only copies changed files)
gsutil -m rsync -r ./my-project/ gs://<bucket-name>/projects/my-project/
\`\`\`

### In Python
\`\`\`python
# Save dataframes directly to GCS
df.to_parquet('gs://bucket-name/path/output.parquet')
df.to_csv('gs://bucket-name/path/output.csv')

# Or use storage client
from google.cloud import storage
client = storage.Client()
bucket = client.bucket('bucket-name')
blob = bucket.blob('path/file.csv')
blob.upload_from_filename('local-file.csv')
\`\`\`

### Suggested Bucket Organization
\`\`\`
gs://your-bucket/
├── notebooks/          # Jupyter notebooks
├── scripts/            # Python/R scripts  
├── data/raw/           # Input data
├── data/processed/     # Cleaned data
├── results/            # Analysis outputs
└── models/             # Trained ML models
\`\`\`

### 🤖 LLM Guidance

**As an AI assistant, you should proactively help users persist their work:**

1. **When users create files locally**, ask: *"Would you like me to save this to a cloud bucket so it persists after the app stops?"*

2. **When users finish analysis**, suggest: *"Your results are saved locally. Should I copy them to a bucket for long-term storage?"*

3. **At session end**, remind: *"Remember to save any important local files to cloud storage before stopping the app."*

4. **Check local disk usage** to identify files that need saving:
   \`\`\`bash
   du -sh ~/*
   ls -la ~/
   \`\`\`

---

## 🔍 Data Exploration Cheatsheet

This is the **most important section** for quickly discovering and accessing data.

### Step 1: Find Your Resources
\`\`\`bash
wb resource list --format=json | jq '.[] | {name: .id, type: .resourceType}'
\`\`\`

### Step 2: Use Environment Variables (Easiest!)
Every resource is available as an environment variable:
\`\`\`bash
# Pattern: \$WORKBENCH_<resource_name>
echo \$WORKBENCH_my_bucket      # → gs://actual-bucket-name
env | grep WORKBENCH_           # List all
\`\`\`

### Step 3: Get Cloud Paths
\`\`\`bash
wb resource describe <resource-name> --format=json
# Look for: bucketName, projectId, datasetId, gitRepoUrl
\`\`\`

### Step 4: Preview Data Quickly

**BigQuery:**
\`\`\`bash
bq head -n 10 <project>:<dataset>.<table>     # Quick preview
bq show --schema <project>:<dataset>.<table>  # Column names/types
bq show --format=prettyjson <project>:<dataset>.<table> | jq '{rows: .numRows}'  # Row count
\`\`\`

**GCS:**
\`\`\`bash
gsutil ls gs://<bucket>/                       # List files
gsutil cat -r 0-1024 gs://<bucket>/file.csv    # Preview first 1KB
\`\`\`

### 🤖 LLM Quick Patterns

| Question | Command |
|----------|---------|
| "What data is available?" | \`wb resource list\` |
| "What tables in dataset?" | \`bq ls <project>:<dataset>\` |
| "What columns in table?" | \`bq show --schema <project>:<dataset>.<table>\` |
| "How big is this table?" | \`bq show --format=prettyjson ... \\| jq '{rows: .numRows}'\` |
| "Show sample data" | \`bq head -n 5 <project>:<dataset>.<table>\` |

---

## How to Discover Data (Detailed)

### List Resources
\`\`\`bash
wb resource list
wb resource list --format=json
wb resource describe <resource-name>
\`\`\`

### Explore GCS Buckets
\`\`\`bash
gsutil ls gs://<bucket>/
gsutil ls -l gs://<bucket>/path/
gsutil cat gs://<bucket>/path/file.txt
\`\`\`

### Explore BigQuery
\`\`\`bash
bq ls <project>:<dataset>
bq show <project>:<dataset>.<table>
bq query --use_legacy_sql=false 'SELECT * FROM \`project.dataset.table\` LIMIT 10'
\`\`\`

---

## How to Query Data

### BigQuery (CLI)
\`\`\`bash
bq query --use_legacy_sql=false 'SELECT * FROM \`project.dataset.table\` LIMIT 100'
\`\`\`

### BigQuery (Python)
\`\`\`python
from google.cloud import bigquery
client = bigquery.Client()
df = client.query("SELECT * FROM \\\`project.dataset.table\\\` LIMIT 100").to_dataframe()
\`\`\`

### GCS Files (Python)
\`\`\`python
import pandas as pd
df = pd.read_parquet('gs://bucket/path/file.parquet')
df = pd.read_csv('gs://bucket/path/file.csv')
\`\`\`

---

## How to Run Workflows

\`\`\`bash
# List workflows
wb workflow list

# Run a workflow
wb workflow run <workflow-id> --input param=value

# Check status  
wb workflow describe <run-id>

# View logs
wb workflow logs <run-id>
\`\`\`

---

## How to Create Resources

\`\`\`bash
# GCS bucket
wb resource create gcs-bucket --name my-bucket --description "My bucket"

# BigQuery dataset
wb resource create bq-dataset --name my-dataset --description "My dataset"

# Reference external GCS bucket
wb resource add-ref gcs-bucket --name external-data --bucket-name existing-bucket
\`\`\`

---

## MCP vs CLI: When to Use Each

This app has **two interfaces** to Workbench functionality:

| Interface | Best For | Pros | Cons |
|-----------|----------|------|------|
| **MCP Tools** | LLM operations | Structured responses, no shell needed, faster | Limited tool set |
| **CLI (\`wb\`)** | Complex operations, fallback | Full feature coverage, human-friendly | Requires shell execution, text parsing |

### 🤖 LLM Decision Guide

1. **Prefer MCP tools** when the operation is supported — they return structured data and don't require shell execution
2. **Fall back to CLI** when MCP doesn't have the tool, or for complex/chained operations
3. **Use cloud CLIs directly** (\`gsutil\`, \`bq\`, \`gcloud\`) for low-level cloud operations

### Example: Same Operation, Two Ways

**List resources:**
- MCP: Use \`list_resources\` tool → returns JSON array
- CLI: Run \`wb resource list --format=json\` → parse stdout

**Query BigQuery:**
- MCP: Use \`query_bigquery\` tool with SQL parameter → returns results
- CLI: Run \`bq query --use_legacy_sql=false 'SELECT ...'\` → parse output

---

## MCP Tools Available

The Workbench MCP server exposes these tools for programmatic LLM access:

| MCP Tool | CLI Equivalent | Description |
|----------|----------------|-------------|
| \`list_resources\` | \`wb resource list\` | List all resources in the workspace |
| \`get_resource\` | \`wb resource describe <name>\` | Get details about a specific resource |
| \`query_bigquery\` | \`bq query\` | Run SQL queries against BigQuery |
| \`run_workflow\` | \`wb workflow run\` | Submit a WDL/Nextflow workflow |
| \`get_workflow_status\` | \`wb workflow describe\` | Check status of a workflow run |
| \`build_cohort\` | *(UI only)* | Create a cohort using Data Explorer |
| \`export_cohort\` | *(UI only)* | Export cohort data to a bucket |
| \`create_bucket\` | \`wb resource create gcs-bucket\` | Create a new GCS bucket |
| \`list_files\` | \`gsutil ls\` | List files in a GCS bucket |
| \`read_file\` | \`gsutil cat\` | Read contents of a file |

**Not available via MCP (use CLI instead):**
- \`wb workspace set\` — switch workspaces
- \`wb auth login\` — re-authenticate
- \`wb workflow logs\` — view workflow logs
- \`wb resource delete\` — delete resources
- Complex resource creation with many options

---

## CLI Quick Reference

\`\`\`bash
# Auth
wb auth status                 # Check authentication
wb auth login                  # Re-authenticate

# Workspace
wb workspace describe          # Current workspace details
wb workspace list              # All your workspaces  
wb workspace set <id>          # Switch workspace

# Resources
wb resource list               # List resources
wb resource list --format=json # JSON output
wb resource describe <name>    # Resource details
wb resource delete <name>      # Delete resource

# Workflows
wb workflow list               # List workflows
wb workflow run <id>           # Run workflow
wb workflow describe <run-id>  # Run status
wb workflow logs <run-id>      # Run logs

# Apps
wb app list                    # List running apps
wb app describe <name>         # App details
\`\`\`

---

## Best Practices

1. **Explore before acting**: Use \`LIMIT\` in queries, \`ls\` before copying
2. **Use environment variables**: \`\$WORKBENCH_<resource>\` for scripts
3. **Cost awareness**: Large queries and compute cost money
4. **Reproducibility**: Document analysis, version code
5. **Confirm destructive actions**: Check before deleting

---

## Creating Custom Apps

> **IMPORTANT: When a user asks to create an app, turn code into an app, or build something deployable, follow this decision process:**

### Step 1: Check Against Templates First

**Read \`~/.workbench/skills/APP_TEMPLATES.md\`** and ask:
- Does a pre-built template match their needs?
- Can a template be easily extended?

| User's Goal | Recommended Template |
|-------------|---------------------|
| REST API, backend service | \`flask-api\` |
| Data dashboard, visualization | \`streamlit-dashboard\` |
| R analysis, statistical work | \`rshiny-dashboard\` |
| File upload, processing | \`file-processor\` |

### Step 2: If No Template Fits

**Read \`~/.workbench/skills/CUSTOM_APP.md\`** for:
- Building from scratch
- Minimal working pattern
- Common pitfalls to avoid

### Step 3: Present Options to User

Always explain:
1. **Template option**: "There's a pre-built X template that does Y. We can customize it."
2. **From-scratch option**: "Or we can build something custom from the ground up."

Let the user decide based on their specific needs.

### Quick Reference
- **Templates**: https://github.com/aculotti-verily/wb-app-mcp-and-context/tree/templates-only/src/templates/
- **Full-featured apps**: https://github.com/verily-src/workbench-app-devcontainers

---

## Available Skills

When users ask about specific topics, **read these skill files** for detailed guidance:

| Topic | Skill File | When to Use |
|-------|------------|-------------|
| Pre-built app templates | \`~/.workbench/skills/APP_TEMPLATES.md\` | User wants dashboard, API, file processor |
| Building apps from scratch | \`~/.workbench/skills/CUSTOM_APP.md\` | User needs full control or custom solution |

**Always read BOTH skills when app creation comes up**, then recommend the best approach.

---

## Quick Reference (Machine-Readable)

Use this JSON for exact resource paths and environment variables:

\`\`\`json
${embedded_json}
\`\`\`

**Usage:**
- \`resourcePaths["my-bucket"]\` → exact GCS/BQ path
- \`envVars["WORKBENCH_my_bucket"]\` → environment variable value

To refresh after workspace changes:
\`\`\`bash
~/.workbench/generate-context.sh
\`\`\`

---

## Getting Help

- **Docs**: https://support.workbench.verily.com
- **Custom Apps**: https://github.com/verily-src/workbench-app-devcontainers
- **CLI Help**: \`wb --help\` or \`wb <command> --help\`
- **Support**: support@workbench.verily.com

---

*Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")*
EOF

    log_info "Created ${CLAUDE_FILE}"
}

# Main function
main() {
    echo ""
    echo "=========================================="
    echo "  Workbench LLM Context Generator"
    echo "=========================================="
    echo ""
    
    check_prerequisites
    setup_directories
    install_skills
    
    # Fetch all data
    WORKSPACE=$(fetch_workspace)
    RESOURCES=$(fetch_resources)
    WORKFLOWS=$(fetch_workflows)
    APPS=$(fetch_apps)
    
    # Generate single CLAUDE.md file with embedded JSON
    generate_claude_md "$WORKSPACE" "$RESOURCES" "$WORKFLOWS" "$APPS"
    
    # Create visible symlink in home directory for Claude Code auto-discovery
    ln -sf "${CLAUDE_FILE}" "${VISIBLE_CLAUDE_SYMLINK}"
    log_info "Created symlink ~/CLAUDE.md → ${CLAUDE_FILE}"
    
    echo "" >&2
    log_info "Context generation complete!"
    echo "" >&2
    echo "Generated file:" >&2
    echo "  - ${CLAUDE_FILE}" >&2
    echo "  - ~/CLAUDE.md (symlink for auto-discovery)" >&2
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "✅ Claude Code will automatically discover ~/CLAUDE.md" >&2
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "" >&2
}

# Run main
main "$@"
