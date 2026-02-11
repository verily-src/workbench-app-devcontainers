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

# Determine user home directory
# Priority: 1) $LLM_CONTEXT_HOME, 2) first arg, 3) $HOME
if [[ -n "${LLM_CONTEXT_HOME:-}" ]]; then
    USER_HOME="${LLM_CONTEXT_HOME}"
elif [[ -n "${1:-}" ]]; then
    USER_HOME="$1"
else
    # Find the primary non-root user's home (typically jupyter)
    if [[ -d "/home/jupyter" ]]; then
        USER_HOME="/home/jupyter"
    else
        USER_HOME="${HOME}"
    fi
fi

# Configuration
CONTEXT_DIR="${USER_HOME}/.workbench"
SKILLS_DIR="${CONTEXT_DIR}/skills"
CLAUDE_FILE="${CONTEXT_DIR}/CLAUDE.md"
# Visible symlink in home directory for Claude Code auto-discovery
VISIBLE_CLAUDE_SYMLINK="${USER_HOME}/CLAUDE.md"

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

## ⚡ Which Approach Do You Need?

```
Do you need Jupyter notebooks?
├── YES → Use workbench-jupyter base image (see "Full-Featured" below)
└── NO
    └── Do you need Workbench CLI (wb) or gcloud?
        ├── YES → Use workbench-tools feature (see "Full-Featured" below)
        └── NO → Use MINIMAL PATTERN (this guide) ✅
```

**Most custom apps should use the MINIMAL PATTERN.** It's simpler and less error-prone.

---

## ✅ Pre-Deploy Checklist

Before deploying, verify:

- [ ] Container is named `application-server`
- [ ] Connected to `app-network` (external: true)
- [ ] HTTP server binds to `0.0.0.0` (not `localhost`)
- [ ] Port is exposed (usually 8080)
- [ ] No syntax errors in `.devcontainer.json` (valid JSON, no trailing commas)
- [ ] `devcontainer-template.json` exists with valid `id` and `name`
- [ ] Test locally with `docker compose up` before deploying

---

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

You are working inside **Verily Workbench**, a secure cloud-based research environment.

---

## ⚡ Quick Rules (Read This First)

| If the user asks... | Do this |
|---------------------|---------|
| About the workspace (name, ID, role, description) | **Use this file** → See "Current Workspace" below |
| For a resource path (bucket, dataset) | **Use this file** → See "Resource Paths" below |
| To query data, list files, or run operations | **Use MCP tools** or CLI |

**Simple rule:** Static info → this file. Actions → MCP/CLI.

---

## What is Verily Workbench?

Verily Workbench enables researchers to:
- Access and analyze biomedical data (clinical, genomics, wearables, imaging)
- Run computational workflows at scale (WDL, Nextflow)
- Collaborate securely with governance and policy enforcement
- Use familiar tools (Jupyter, RStudio, VS Code) in the cloud

---

## 📍 Current Workspace

> **Answer "What workspace am I in?" with this section.**

| Property | Value |
|----------|-------|
| **Name** | ${ws_name} |
| **ID** | \`${ws_id}\` |
| **Description** | ${ws_desc} |
| **Cloud** | ${ws_cloud} |
| **Project** | \`${project_display}\` |
| **Your Role** | ${ws_role} |
| **User** | ${ws_user} |
| **Organization** | ${ws_org:-"—"} |
| **Server** | ${ws_server:-"—"} |

**Example response:** *"You're in **${ws_name}** (\`${ws_id}\`), a ${ws_cloud} workspace where you have ${ws_role} access."*

---

## 🗂️ Resource Paths (Use for "What's the path for X?")

\`\`\`json
${embedded_json}
\`\`\`

**How to use:**
- \`resourcePaths["my-bucket"]\` → \`gs://actual-bucket-name\`
- Environment variable: \`\$WORKBENCH_my_bucket\`

---

## ⚠️ Data Persistence Warning

> **LOCAL FILES ARE LOST WHEN THE APP STOPS.** Always save important work to cloud buckets.

### Available Buckets
${bucket_list}

### Quick Save Commands
\`\`\`bash
gsutil cp file.ipynb gs://BUCKET/notebooks/           # Single file
gsutil -m cp -r ./results/ gs://BUCKET/results/       # Directory
\`\`\`

**🤖 Proactively ask users:** *"Want me to save this to a bucket so it persists?"*

---

## 🔍 Data Exploration (Most Common Tasks)

### Find Resources
\`\`\`bash
wb resource list                    # List all
wb resource describe <name>         # Details
env | grep WORKBENCH_               # Environment variables
\`\`\`

### Preview BigQuery Data
\`\`\`bash
bq ls PROJECT:DATASET                              # List tables
bq show --schema PROJECT:DATASET.TABLE             # Schema
bq head -n 10 PROJECT:DATASET.TABLE                # Sample rows
\`\`\`

### Browse GCS Files
\`\`\`bash
gsutil ls gs://BUCKET/                             # List
gsutil cat gs://BUCKET/file.txt | head             # Preview
\`\`\`

---

## 🔧 MCP Tools vs CLI

| Use MCP Tools For | Use CLI For |
|-------------------|-------------|
| \`list_resources\`, \`get_resource\` | Complex operations |
| \`query_bigquery\` | \`wb workflow logs\` |
| \`run_workflow\` | \`wb resource delete\` |
| Structured responses | Full feature coverage |

**Prefer MCP when available** — it's faster and returns structured data.

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

## Python Examples

\`\`\`python
# BigQuery
from google.cloud import bigquery
client = bigquery.Client()
df = client.query("SELECT * FROM \\\`project.dataset.table\\\` LIMIT 100").to_dataframe()

# GCS Files
import pandas as pd
df = pd.read_parquet('gs://bucket/path/file.parquet')

# Save to GCS
df.to_parquet('gs://bucket/output.parquet')
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

**Two approaches depending on complexity:**

### Simple Apps (Recommended)
Workbench custom apps need exactly **three things**:
1. Container named \`application-server\`
2. Connected to \`app-network\` (external Docker network)
3. HTTP server on a port

⚠️ **Avoid complexity:** Devcontainer features and startup scripts often fail.

**📖 For detailed guide:** \`Read ~/.workbench/skills/CUSTOM_APP.md\`

### Full-Featured Apps
For apps needing Workbench CLI, gcloud, etc.:
📦 https://github.com/verily-src/workbench-app-devcontainers

---

## Available Skills

When users ask about specific topics, **read these skill files** for detailed guidance:

| Topic | Skill File |
|-------|------------|
| Creating custom apps | \`~/.workbench/skills/CUSTOM_APP.md\` |

**How to use:** When the topic comes up, read the skill file first.

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
