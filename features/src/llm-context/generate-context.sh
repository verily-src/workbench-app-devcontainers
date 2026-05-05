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
#     - resourceType: GCS_BUCKET, BQ_DATASET, GIT_REPO, GCS_OBJECT, BQ_TABLE (GCP)
#                       AWS_S3_STORAGE_FOLDER, AWS_AURORA_DATABASE, AWS_AURORA_DATABASE_REFERENCE (AWS)
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
CONTEXT_DIR="${HOME}/.claude"
SKILLS_DIR="${CONTEXT_DIR}/skills"
CLAUDE_FILE="${CONTEXT_DIR}/CLAUDE.md"

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
        log_error "  wb auth login   (GCP: add --mode=APP_DEFAULT_CREDENTIALS inside Workbench apps)"
        log_error "  wb workspace set <workspace-id>"
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
# $1: cloud_platform — "GCP" (default) or "AWS"
install_skills() {
    local cloud_platform="${1:-GCP}"
    log_info "Installing skill files..."
    
    # Create CUSTOM_APP.md skill (full version, embedded)
    log_info "Creating CUSTOM_APP.md skill..."
    cat > "${SKILLS_DIR}/CUSTOM_APP.md" << 'SKILL_EOF'
# Creating Custom Workbench Apps

**Practical guide for creating simple, reliable Workbench apps.**

> **Official Reference:** https://github.com/verily-src/workbench-app-devcontainers
> 
> **Quick Start Script:** Use \`./scripts/create-custom-app.sh\` for auto-generated app structure!

---

## 🚀 Quick Start (Recommended)

The official repo has a script that generates a complete app structure:

\`\`\`bash
# Clone the official repo
git clone https://github.com/verily-src/workbench-app-devcontainers.git
cd workbench-app-devcontainers

# Run the quick start script
./scripts/create-custom-app.sh my-app quay.io/jupyter/base-notebook 8888 jovyan /home/jovyan
\`\`\`

This generates all required files in \`src/my-app/\` with correct structure.

---

## ⚠️ Critical Requirements

### 1. File Structure (MUST follow this exactly)

\`\`\`
your-repo/
├── .devcontainer.json         ← MUST be at repo ROOT (not in a folder!)
├── docker-compose.yaml
├── Dockerfile
├── devcontainer-template.json
└── app/
    └── your_app.py
\`\`\`

**⚠️ CRITICAL:** Workbench expects \`.devcontainer.json\` at the **repo ROOT**, NOT inside a \`.devcontainer/\` folder!

### 2. Container Requirements

Workbench custom apps need exactly **three things**:
1. Container named \`application-server\`
2. Connected to \`app-network\` (external Docker network)
3. HTTP server on a port

---

## The Working Pattern (Copy This)

### File 1: \`.devcontainer.json\`

**Location:** Repo ROOT (same level as docker-compose.yaml)

\`\`\`json
{
  "name": "Your App Name",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/app",
  "remoteUser": "root"
}
\`\`\`

**⚠️ CRITICAL settings:**
- \`"dockerComposeFile": "docker-compose.yaml"\` - Same directory (both at root)
- \`"workspaceFolder": "/app"\` - Should match WORKDIR in Dockerfile
- File MUST be named \`.devcontainer.json\` at repo root

### File 2: \`docker-compose.yaml\`

**Location:** Repository root

\`\`\`yaml
services:
  app:
    container_name: "application-server"
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    ports:
      - "8080:8080"
    volumes:
      - .:/app:cached
    networks:
      - app-network

networks:
  app-network:
    external: true
\`\`\`

**⚠️ CRITICAL settings:**
- \`container_name: "application-server"\` - Workbench looks for this exact name
- \`networks: app-network\` with \`external: true\` - Required for Workbench connectivity
- \`volumes: - .:/app:cached\` - Mounts code for live updates

### File 3: \`Dockerfile\`

\`\`\`dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# CRITICAL: Must bind to 0.0.0.0 for Workbench proxy
CMD ["python", "app.py"]
\`\`\`

### File 4: \`devcontainer-template.json\`

\`\`\`json
{
  "id": "your-app-name",
  "description": "Your app description",
  "version": "1.0.0",
  "name": "Your App Name",
  "options": {},
  "platforms": ["Any"]
}
\`\`\`

---

## Common Mistakes Checklist

Before deploying, verify:

- [ ] \`.devcontainer.json\` is at repo ROOT (NOT in a folder!)
- [ ] \`dockerComposeFile\` is \`"docker-compose.yaml"\` (same directory)
- [ ] \`container_name\` is exactly \`"application-server"\`
- [ ] Network is \`app-network\` with \`external: true\`
- [ ] Flask/server binds to \`0.0.0.0\` (not \`localhost\`)
- [ ] Volume mount included for code updates

---

## ⚠️ Workbench App URLs (CRITICAL)

**When accessing your app, you MUST use this format:**

\`\`\`
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
\`\`\`

### Get App UUID:
\`\`\`bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
\`\`\`

### ❌ WRONG Formats (Will fail)
\`\`\`
https://abc123-def456.workbench-app.verily.com/  ← WRONG
http://localhost:8080/                            ← WRONG
\`\`\`

---

## Flask App Example

\`\`\`python
from flask import Flask
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return '<h1>Hello Workbench!</h1>'

if __name__ == '__main__':
    # CRITICAL: host='0.0.0.0' required for Workbench proxy
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
\`\`\`

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| App fails to create / No container | \`devcontainer.json\` in wrong location | Move to repo ROOT as \`.devcontainer.json\` |
| App fails to create | \`devcontainer.json\` in \`.devcontainer/\` folder | Workbench needs it at ROOT, not in folder |
| "Bad Request" error | Wrong URL format | Use \`workbench.verily.com/app/UUID/proxy/PORT/\` |
| Server not accessible | Bound to \`localhost\` | Change to \`host='0.0.0.0'\` |
| Container restart loop | Process exits immediately | Ensure server runs continuously |

---

## Deployment

In Workbench UI, create custom app with:
- **Repository:** \`https://github.com/YOUR-ORG/YOUR-REPO.git\`
- **Branch:** \`main\`
- **Folder:** \`.\` (root) or \`src/YOUR-APP-NAME\` if in monorepo

---

## Local Testing

\`\`\`bash
# Create required network
docker network create app-network

# Build and run
docker compose build
docker compose up

# Access at http://localhost:8080
\`\`\`

---

## Reference Implementations

All examples: https://github.com/verily-src/workbench-app-devcontainers/tree/master/src

| App | Description | Port |
|-----|-------------|------|
| \`playground/\` | Simple multi-service example | 8080 |
| \`vscode/\` | VS Code Server | 8443 |
| \`r-analysis/\` | RStudio | 8787 |
| \`workbench-jupyter/\` | JupyterLab with tools | 8888 |

---

## When to Use Features

Sometimes you need the full-featured approach:

| Need | Solution |
|------|----------|
| Workbench CLI (\`wb\`) | Use \`workbench-tools\` feature |
| LLM/MCP integration | Use \`wb-mcp-server\` feature |
| Pre-authenticated gcloud | Use \`workbench-tools\` feature |

**If you need these, use the full \`workbench-app-devcontainers\` repo as your base.**
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

## How to Use a Template

### Copy and Customize
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
2. If truly custom, read `~/.claude/skills/CUSTOM_APP.md`
TEMPLATES_SKILL_EOF

    # Create DASHBOARD_BUILDER.md skill (full version, embedded)
    log_info "Creating DASHBOARD_BUILDER.md skill..."
    cat > "${SKILLS_DIR}/DASHBOARD_BUILDER.md" << 'DASHBOARD_SKILL_EOF'
# Web Apps & Dashboards Skill

**Build interactive web apps, dashboards, and visualizations that run on a port in Workbench.**

> **Triggers:** 
> - "Create a dashboard", "visualize data", "build charts"
> - "Run a Flask/Streamlit/FastAPI app"
> - "Display data in the browser", "interactive UI"
> - Any web app that serves content on a port

---

## 🌐 Workbench Proxy & Web Apps Best Practices

### Proxy URL Format

The proxy URL is the **only valid way** to access web apps in Workbench:
\`\`\`
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
\`\`\`

Retrieve the App UUID automatically:
\`\`\`bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
\`\`\`

### ✅ Correct URL Examples
\`\`\`
https://workbench.verily.com/app/abc123-def456-789/proxy/8080/
https://workbench.verily.com/app/abc123-def456-789/proxy/8501/index.html
https://workbench.verily.com/app/abc123-def456-789/proxy/8000/dashboard.html
\`\`\`

### ❌ WRONG URL Formats (These WILL fail)
\`\`\`
https://abc123-def456.workbench-app.verily.com/  ← WRONG: "Bad Request" error
https://workbench-app.verily.com/abc123-def456/  ← WRONG: Invalid domain
http://localhost:8080/                            ← WRONG: Not accessible externally
https://abc123-def456/workbench.verily.com/       ← WRONG: Reversed format
file:///home/jupyter/dashboard.html               ← WRONG: JavaScript blocked
\`\`\`

### ⚠️ Common Issue: JavaScript API Calls Failing

**Problem:** JavaScript using absolute paths fails through Workbench proxy

**Symptoms:**
- Dashboard loads but shows no data
- Charts remain empty with "-" placeholders  
- Browser console shows 404 errors for API calls
- Flask/server logs show requests for \`/\` but NOT \`/api/*\` endpoints

### ✅ Solution: Use Relative Paths (TESTED & CONFIRMED)

**Always use relative paths (no leading \`/\`) for fetch/AJAX calls:**

\`\`\`javascript
// ✅ CORRECT - relative paths work through proxy
fetch('api/metadata')
fetch('api/data?filter=value')

// ❌ WRONG - absolute paths fail
fetch('/api/metadata')  
fetch('/api/data?filter=value')
\`\`\`

### Alternative: Embed Data in HTML (For Static Dashboards)

If you don't need dynamic filtering, embed data directly in the template:

**Python (Flask):**
\`\`\`python
@app.route('/')
def index():
    data = get_data_from_bigquery()
    return render_template('dashboard.html', data_json=json.dumps(data))
\`\`\`

**HTML Template:**
\`\`\`html
<script>
const data = {{ data_json|safe }};
// Use data directly, no fetch calls needed
renderChart(data);
</script>
\`\`\`

**When to use:** Static dashboards, large datasets that don't change, or when filters can be client-side only.

### Testing Checklist

Before deploying:
- [ ] All \`fetch()\` calls use relative paths (\`'api/...'\` not \`'/api/...'\`)
- [ ] Test locally: \`curl http://localhost:PORT/api/endpoint\`
- [ ] Server logs show API requests arriving
- [ ] App UUID obtained (not using placeholder \`[APP_UUID]\`)

---

## Workflow

### Step 1: Understand Requirements

Ask the user:
1. **Data source?** BigQuery table, CSV in bucket, or local file?
2. **Visualizations?** Charts (bar, line, scatter), tables, filters?
3. **Interactivity?** Static display or dynamic filtering?

### Step 2: Auto-Detect Environment

**Always run these commands first:**

\`\`\`bash
# Get app UUID (REQUIRED for final URL)
APP_UUID=\$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)
echo "App UUID: \$APP_UUID"

# Verify Python
python3 --version

# Check working directory
pwd
\`\`\`

### Step 3: Install Dependencies

\`\`\`bash
pip install flask flask-cors pandas plotly google-cloud-bigquery db-dtypes
\`\`\`

> **Note:** \`db-dtypes\` is required for BigQuery to properly convert data types for pandas.

### Step 4: Create Dashboard Structure

\`\`\`
dashboard/
├── app.py              # Flask server
├── templates/
│   └── index.html      # Dashboard HTML
└── static/
    └── style.css       # Optional styling
\`\`\`

---

## Working Template: BigQuery Dashboard

**app.py:**
\`\`\`python
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from google.cloud import bigquery

app = Flask(__name__)
CORS(app)

_data_cache = None

def get_bigquery_data():
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    
    client = bigquery.Client()
    query = """
    SELECT *
    FROM \\\`YOUR_PROJECT.YOUR_DATASET.YOUR_TABLE\\\`
    LIMIT 1000
    """
    df = client.query(query).to_dataframe()
    _data_cache = df.to_dict(orient='records')
    return _data_cache

@app.route('/')
def index():
    return render_template('index.html')

@app.route('api/data')  # NO leading slash!
def get_data():
    try:
        data = get_bigquery_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('api/metadata')
def get_metadata():
    try:
        data = get_bigquery_data()
        return jsonify({
            "columns": list(data[0].keys()) if data else [],
            "row_count": len(data)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # CRITICAL: host='0.0.0.0' required for Workbench proxy access
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
\`\`\`

**templates/index.html:**
\`\`\`html
<!DOCTYPE html>
<html>
<head>
    <title>Data Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .chart { background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .error { color: #d32f2f; padding: 20px; background: #ffebee; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Data Dashboard</h1>
        <div id="metadata" class="chart"><div id="metadata-content">Loading...</div></div>
        <div id="chart1" class="chart"><div id="chart-content">Loading...</div></div>
    </div>
    <script>
        // CRITICAL: Use relative paths (no leading slash!)
        async function loadData() {
            try {
                const response = await fetch('api/data');  // Relative!
                if (!response.ok) throw new Error('HTTP ' + response.status);
                const data = await response.json();
                
                const cols = Object.keys(data[0]);
                const numCol = cols.find(c => typeof data[0][c] === 'number') || cols[1];
                
                Plotly.newPlot('chart-content', [{
                    x: data.slice(0,20).map(r => r[cols[0]]),
                    y: data.slice(0,20).map(r => r[numCol]),
                    type: 'bar'
                }]);
            } catch (e) {
                document.getElementById('chart-content').innerHTML = '<div class="error">Error: ' + e.message + '</div>';
            }
        }
        loadData();
    </script>
</body>
</html>
\`\`\`

---

## Step 5: Test & Launch

\`\`\`bash
# Get app UUID
APP_UUID=\$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)

# Start server
cd dashboard
nohup python3 app.py > server.log 2>&1 &

# Test locally
curl -s http://localhost:8080/api/metadata | jq .

echo "Dashboard at: https://workbench.verily.com/app/\${APP_UUID}/proxy/8080/"
\`\`\`

---

## ⚠️ Critical Flask Configuration

\`\`\`python
# ❌ WRONG - proxy cannot reach your app
app.run(host='localhost', port=8080)

# ✅ CORRECT - accessible through Workbench proxy
app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
\`\`\`

**Required settings:**
- \`host='0.0.0.0'\` - Allows external connections (not just localhost)
- \`threaded=True\` - Handles concurrent users
- \`debug=False\` - Security (don't expose debug info)

**Restart after code changes:**
\`\`\`bash
pkill -f "python3 app.py"
python3 app.py &
\`\`\`

**Browser not showing changes?** Hard refresh: \`Ctrl+Shift+R\` or \`Cmd+Shift+R\`

---

## Troubleshooting Checklist

| Issue | Check | Fix |
|-------|-------|-----|
| Data doesn't load | Path format | Change \`fetch('/api/...')\` to \`fetch('api/...')\` |
| 404 errors | Server running? | \`ps aux | grep python\` |
| CORS error | CORS setup | Ensure \`CORS(app)\` is added |
| BQ error | Auth | Check \`gcloud auth list\` |
| Blank page | Console errors | Check browser DevTools |
| Works locally, fails via URL | Host binding | Change \`localhost\` to \`0.0.0.0\` |
| Gateway timeout | Server/UUID | Check server running + correct UUID |
| Address in use | Port conflict | \`kill \$(lsof -t -i :8080)\` |
| Changes not showing | Cache/restart | Hard refresh + restart server |

---

## Common Pitfalls

- ❌ \`fetch('/api/data')\` — **Use** \`fetch('api/data')\` (no leading slash)
- ❌ \`host='localhost'\` — **Use** \`host='0.0.0.0'\` (allows proxy access)
- ❌ Placeholder \`[APP_UUID]\` — **Always get real UUID** with \`wb app list\`
- ❌ Forgetting to restart server after code changes
- ❌ Not checking server logs when debugging
DASHBOARD_SKILL_EOF

    # Create WORKFLOW_TROUBLESHOOT.md skill (full version, embedded)
    log_info "Creating WORKFLOW_TROUBLESHOOT.md skill..."
    cat > "${SKILLS_DIR}/WORKFLOW_TROUBLESHOOT.md" << 'WORKFLOW_SKILL_EOF'
# WDL Workflow Troubleshooting Skill

**Trigger:** User asks to troubleshoot, debug, or fix a failed workflow.

## ⚡ LLM Behavior: Be Proactive!

**Once the user confirms which job to investigate, DO NOT ask which diagnostic steps to run.** Instead:
1. **Run all diagnostic commands automatically** (Steps 2-4 at minimum)
2. **Analyze the results** and identify the root cause
3. **Report your diagnosis** with evidence (error messages, exit codes, log snippets)
4. **Propose a fix** with specific changes
5. **THEN ask** if they want you to apply the fix or investigate further

❌ Don't say: "Would you like me to check the logs?"
✅ Do say: "I checked the logs and found an OOM error. The task requested 8GB but needed more. I recommend increasing memory to 16GB in the runtime block."

---

## Quick Diagnosis (Start Here)

\`\`\`bash
# 1. Find failed jobs
wb workflow job list --format=json | jq -r '.[] | select(.status=="FAILED") | "\(.id)\t\(.workflowName)\t\(.startTime)"'

# 2. Get error message (replace JOB_ID)
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage // "No message"'

# 3. Find failed task
wb workflow job task list --job=<JOB_ID> --format=json | jq -r '.[] | select(.status=="FAILED") | .name'

# 4. Get task error + logs
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json | jq '{stderr, stdout, exitCode, failureMessage}'
\`\`\`

**After running these 4 commands, you'll know:** which job failed, why, which task, and where logs are.

---

## Step-by-Step Guide

### Step 1: Identify Failed Job

\`\`\`bash
# List all failed jobs
wb workflow job list --format=json | jq '.[] | select(.status == "FAILED") | {id, workflowName, status, startTime, endTime}'
\`\`\`

**For batch jobs:**
\`\`\`bash
# List failed sub-jobs within a batch
wb workflow job batch list --job=<JOB_ID> --format=json | jq '.[] | select(.status == "FAILED") | {id, status}'
\`\`\`

**Ask user:** Confirm which job ID to investigate (if multiple failed jobs).

---

### Step 2: Get Job Details & Inputs

\`\`\`bash
wb workflow job describe --job=<JOB_ID> --format=json | jq '{failureMessage, inputs, outputs}'
\`\`\`

---

### Step 3: Find Failed Task & Get Logs

\`\`\`bash
# List all tasks with status
wb workflow job task list --job=<JOB_ID> --format=json | jq '.[] | {name, status, exitCode}'

# Get failed task details
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json
\`\`\`

**Extract log URLs:**
\`\`\`bash
# Get stderr and stdout URLs
TASK_INFO=\$(wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json)
STDERR_URL=\$(echo \$TASK_INFO | jq -r '.stderr')
STDOUT_URL=\$(echo \$TASK_INFO | jq -r '.stdout')

echo "stderr: \$STDERR_URL"
echo "stdout: \$STDOUT_URL"
\`\`\`

---

### Step 4: Pull and Analyze Task Logs

#### Read Log Contents

\`\`\`bash
# Read stderr (usually contains errors)
gsutil cat "\$STDERR_URL" 2>/dev/null | tail -100

# Read stdout
gsutil cat "\$STDOUT_URL" 2>/dev/null | tail -100

# Search for common error patterns
gsutil cat "\$STDERR_URL" 2>/dev/null | grep -i -E "error|exception|failed|denied|killed|oom|memory|disk|timeout" | head -30
\`\`\`

#### Common Log File Patterns

Cromwell execution logs are typically at:
\`\`\`
gs://<execution-bucket>/<workflow-id>/<call-name>/execution/
├── stdout          # Task standard output
├── stderr          # Task standard error  
├── script          # The actual command that ran
├── rc              # Return code (exit code)
└── script.submit   # Submission script
\`\`\`

**One-liner to read all execution files:**
\`\`\`bash
# Find execution directory from task describe, then:
EXEC_DIR=\$(echo \$TASK_INFO | jq -r '.executionDirectory // empty')
if [ -n "\$EXEC_DIR" ]; then
  echo "=== script ===" && gsutil cat "\$EXEC_DIR/script" 2>/dev/null
  echo "=== rc ===" && gsutil cat "\$EXEC_DIR/rc" 2>/dev/null
  echo "=== stderr (last 50 lines) ===" && gsutil cat "\$EXEC_DIR/stderr" 2>/dev/null | tail -50
fi
\`\`\`

---

### Step 5: Check Resource Allocation & Usage

#### What Was Requested (from WDL runtime)

\`\`\`bash
# Get workflow definition to see runtime requirements
wb workflow describe --workflow=<WORKFLOW_ID> --format=json | jq '.sourceUrl'

# Read WDL file
gsutil cat gs://<bucket>/<path>/workflow.wdl | grep -A10 "runtime {"
\`\`\`

#### Check Actual Resource Usage (GCP Batch)

\`\`\`bash
# For GCP Cromwell jobs, get batch job details
gcloud batch jobs list --filter="status.state=FAILED" --format="table(name,status.state,createTime)"

# Describe specific batch job
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '{
  status: .status.state,
  statusEvents: .status.statusEvents,
  taskGroups: .taskGroups[0].taskSpec.computeResource
}'
\`\`\`

#### Memory-Specific Checks

\`\`\`bash
# Check if OOM (Out of Memory) killed the task
gsutil cat "\$STDERR_URL" 2>/dev/null | grep -i -E "oom|out of memory|killed|cannot allocate|memory"

# Check what memory was requested in batch job
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '.taskGroups[0].taskSpec.computeResource.memoryMib'

# Check dmesg/syslog for OOM events (if available in logs)
gsutil cat "\$STDERR_URL" 2>/dev/null | grep -i "killed process"
\`\`\`

---

### Step 6: Diagnose by Error Type

#### Memory Issues (OOM)

**Symptoms:**
- Exit code 137 (SIGKILL) or 143
- "Killed" in stderr
- "Cannot allocate memory"
- Task succeeded locally but fails at scale

**Diagnosis:**
\`\`\`bash
# Check requested memory
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '.taskGroups[0].taskSpec.computeResource'

# Look for memory errors in logs
gsutil cat "\$STDERR_URL" 2>/dev/null | grep -i -E "memory|oom|killed|malloc"
\`\`\`

**Fix:** Increase \`memory\` in WDL runtime block:
\`\`\`wdl
runtime {
  memory: "32G"  # Increase from previous value
}
\`\`\`

#### Disk Issues

**Symptoms:**
- "No space left on device"
- "Disk quota exceeded"

**Diagnosis:**
\`\`\`bash
gsutil cat "\$STDERR_URL" 2>/dev/null | grep -i -E "space|disk|quota"
\`\`\`

**Fix:** Increase disk in WDL runtime:
\`\`\`wdl
runtime {
  disks: "local-disk 200 SSD"  # Increase size
}
\`\`\`

#### Input File Issues

**Symptoms:**
- "FileNotFoundException"
- "Localization failed"
- File not found errors

**Diagnosis:**
\`\`\`bash
# Check if input files exist
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.inputs | to_entries[] | .value' | while read path; do
  if [[ \$path == gs://* ]]; then
    echo -n "\$path: " && gsutil ls "\$path" 2>&1 | head -1
  fi
done
\`\`\`

#### Permission Issues

**Symptoms:**
- "Permission denied"
- "Access denied"
- 403 errors

**Diagnosis:**
\`\`\`bash
# Check service account permissions
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '.taskGroups[0].taskSpec.serviceAccount'

# Test bucket access
gsutil ls gs://<bucket>/ 2>&1 | head -5
\`\`\`

---

### Step 7: Propose Solution

Based on diagnosis, recommend one of:

| Issue | Solution Template |
|-------|-------------------|
| **OOM** | "Increase memory from X to Y in the runtime block" |
| **Disk full** | "Increase disk size from X to Y GB" |
| **Missing input** | "Input file doesn't exist. Verify path: \`gsutil ls <path>\`" |
| **Permission** | "Service account lacks access. Grant \`roles/storage.objectViewer\` on bucket" |
| **Timeout** | "Task exceeded time limit. Increase \`maxRetries\` or optimize task" |
| **Docker** | "Image pull failed. Verify image exists and is accessible" |

**Re-run after fixing:**
\`\`\`bash
wb workflow job run --workflow=<WORKFLOW_ID> --inputs=<INPUTS_JSON>
\`\`\`

---

## Quick Reference

### Error → Cause → Fix

| Exit Code | Meaning | Common Fix |
|-----------|---------|------------|
| 1 | General error | Check stderr for details |
| 2 | Misuse of command | Check script syntax |
| 126 | Permission problem | Check file permissions |
| 127 | Command not found | Check PATH, container image |
| 137 | SIGKILL (OOM) | **Increase memory** |
| 139 | Segfault | Check input data, memory |
| 143 | SIGTERM | Task timeout or preemption |

---

## Workbench-Specific Notes

- **Log retention:** Cromwell logs persist in workspace execution bucket
- **Batch jobs:** Each sub-job has independent logs; troubleshoot specific failed sub-job
- **VPC-SC:** Run \`gcloud batch\` commands from within workspace app
- **Preemption:** If using spot VMs, set \`preemptible: 0\` for reliability
WORKFLOW_SKILL_EOF

    # Create scientific skills directory and index
    log_info "Creating scientific skills..."
    mkdir -p "${SKILLS_DIR}/scientific"
    
    # Create SCIENTIFIC_SKILLS_INDEX.md
    cat > "${SKILLS_DIR}/SCIENTIFIC_SKILLS_INDEX.md" << 'SCIENTIFIC_SKILLS_EOF'
# Scientific Skills Index

**This file routes Claude to domain-specific scientific skills.**
Workbench skills (workflows, dashboards, custom apps) are handled directly by `CLAUDE.md`.

---

## ⚡ Quick Navigation

| User Says... | Read This Skill |
|--------------|-----------------|
| "single-cell" / "RNA-seq" / "scanpy" / "differential expression" | `scientific/BIOINFORMATICS.md` |
| "molecule" / "SMILES" / "drug" / "RDKit" / "ChEMBL" / "target" | `scientific/DRUG_DISCOVERY.md` |
| "gene" / "protein" / "variant" / "UniProt" / "Ensembl" / "PDB" | `scientific/GENOMICS_DATABASES.md` |
| "machine learning" / "sklearn" / "statistics" / "plot" | `scientific/DATA_ANALYSIS.md` |
| "clinical trial" / "PubMed" / "survival analysis" | `scientific/CLINICAL.md` |

---

## Domain Skills

### 🧬 Bioinformatics (`scientific/BIOINFORMATICS.md`)
Single-cell analysis, differential expression, sequence analysis, RNA velocity.
**Packages:** scanpy, anndata, biopython, pydeseq2, scvelo

### 💊 Drug Discovery (`scientific/DRUG_DISCOVERY.md`)
Cheminformatics, molecular ML, bioactivity databases, target identification.
**Packages/APIs:** rdkit, deepchem, chembl, drugbank, opentargets

### 🔬 Genomics Databases (`scientific/GENOMICS_DATABASES.md`)
Gene annotations, protein data, variant interpretation, 3D structures.
**APIs:** ensembl, uniprot, clinvar, pdb

### 📊 Data Analysis (`scientific/DATA_ANALYSIS.md`)
Machine learning, statistics, visualization.
**Packages:** scikit-learn, statsmodels, plotly, seaborn

### 🏥 Clinical (`scientific/CLINICAL.md`)
Clinical trials, literature search, survival analysis.
**APIs:** clinicaltrials.gov, pubmed

---

## Adding New Skills

To add skills from [claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills):

1. Copy the `SKILL.md` file to `scientific/<skill-name>.md`
2. Add a row to the Quick Navigation table above
3. Add a domain section below
SCIENTIFIC_SKILLS_EOF

    # Create BIOINFORMATICS.md
    cat > "${SKILLS_DIR}/scientific/BIOINFORMATICS.md" << 'BIOINFO_EOF'
# Bioinformatics Skills

**Trigger:** Single-cell, RNA-seq, sequences, differential expression, trajectory.

## Quick Reference
| Task | Package | Import |
|------|---------|--------|
| Single-cell workflow | scanpy | `import scanpy as sc` |
| Differential expression | pydeseq2 | `from pydeseq2 import DeseqDataSet` |
| Sequence analysis | biopython | `from Bio import SeqIO` |
| RNA velocity | scvelo | `import scvelo as scv` |

## Scanpy Workflow
```python
import scanpy as sc
adata = sc.read_h5ad('data.h5ad')
sc.pp.calculate_qc_metrics(adata, inplace=True)
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
sc.tl.pca(adata)
sc.pp.neighbors(adata)
sc.tl.umap(adata)
sc.tl.leiden(adata)
sc.tl.rank_genes_groups(adata, 'leiden')
sc.pl.umap(adata, color='leiden')
```

## PyDESeq2 (Differential Expression)
```python
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats
dds = DeseqDataSet(counts=counts.T, metadata=metadata, design_factors='condition')
dds.deseq2()
stat_res = DeseqStats(dds, contrast=['condition', 'treated', 'control'])
results = stat_res.results_df
sig = results[(results['padj'] < 0.05) & (abs(results['log2FoldChange']) > 1)]
```

## Biopython
```python
from Bio import SeqIO, Entrez
Entrez.email = "email@example.com"
# Parse FASTA
for record in SeqIO.parse('seq.fasta', 'fasta'):
    print(record.id, len(record.seq))
# NCBI fetch
handle = Entrez.efetch(db="nucleotide", id="NM_001301717", rettype="fasta")
```

Install: `pip install scanpy anndata pydeseq2 biopython scvelo`
BIOINFO_EOF

    # Create DRUG_DISCOVERY.md
    cat > "${SKILLS_DIR}/scientific/DRUG_DISCOVERY.md" << 'DRUGDISC_EOF'
# Drug Discovery Skills

**Trigger:** Molecules, SMILES, drugs, fingerprints, ADMET, targets, bioactivity.

## Quick Reference
| Task | Tool | Access |
|------|------|--------|
| Molecular properties | rdkit | `from rdkit import Chem` |
| ADMET prediction | deepchem | `import deepchem as dc` |
| Bioactivity (IC50, Ki) | ChEMBL | REST API |
| Drug info | DrugBank | REST API |
| Target-disease | Open Targets | GraphQL |

## RDKit
```python
from rdkit import Chem
from rdkit.Chem import Descriptors, AllChem, DataStructs

mol = Chem.MolFromSmiles('CC(=O)OC1=CC=CC=C1C(=O)O')  # Aspirin
mw = Descriptors.MolWt(mol)
logp = Descriptors.MolLogP(mol)
hbd = Descriptors.NumHDonors(mol)
hba = Descriptors.NumHAcceptors(mol)

# Fingerprint similarity
fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, radius=2)
fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, radius=2)
similarity = DataStructs.TanimotoSimilarity(fp1, fp2)
```

## ChEMBL API
```python
from chembl_webresource_client.new_client import new_client
molecule = new_client.molecule
activity = new_client.activity
# Search compound
aspirin = molecule.filter(pref_name__iexact='aspirin')[0]
# Get activities for target
acts = activity.filter(target_chembl_id='CHEMBL230', pchembl_value__gte=6)
```

## Open Targets API
```python
import requests
query = '''query { target(ensemblId: "ENSG00000157764") {
  approvedSymbol
  associatedDiseases { rows { disease { name } score } }
}}'''
r = requests.post("https://api.platform.opentargets.org/api/v4/graphql", json={'query': query})
```

Install: `pip install rdkit deepchem chembl_webresource_client`
DRUGDISC_EOF

    # Create GENOMICS_DATABASES.md
    cat > "${SKILLS_DIR}/scientific/GENOMICS_DATABASES.md" << 'GENOMICS_EOF'
# Genomics Databases Skills

**Trigger:** Genes, proteins, variants, structures, Ensembl, UniProt, ClinVar, PDB.

## Quick Reference
| Need | Database | API |
|------|----------|-----|
| Gene annotations | Ensembl | REST |
| Protein data | UniProt | REST |
| Variant pathogenicity | ClinVar | E-utilities |
| 3D structures | PDB | REST |

## Ensembl
```python
import requests
SERVER = "https://rest.ensembl.org"
# Gene lookup
gene = requests.get(f"{SERVER}/lookup/symbol/homo_sapiens/BRCA1",
                   headers={"Content-Type": "application/json"}).json()
# Sequence
seq = requests.get(f"{SERVER}/sequence/id/{gene['id']}").json()
```

## UniProt
```python
import requests
# Search protein
r = requests.get("https://rest.uniprot.org/uniprotkb/search",
    params={"query": "gene:TP53 AND organism_id:9606", "format": "json"})
# Get by ID
protein = requests.get("https://rest.uniprot.org/uniprotkb/P04637.json").json()
```

## ClinVar
```python
from Bio import Entrez
Entrez.email = "email@example.com"
handle = Entrez.esearch(db="clinvar", term="BRCA1[gene] AND pathogenic[clinsig]")
record = Entrez.read(handle)
```

## PDB
```python
import requests
# Get structure
structure = requests.get("https://data.rcsb.org/rest/v1/core/entry/1TUP").json()
# Download PDB file
pdb = requests.get("https://files.rcsb.org/download/1TUP.pdb").text
```

Install: `pip install biopython requests`
GENOMICS_EOF

    # Create DATA_ANALYSIS.md
    cat > "${SKILLS_DIR}/scientific/DATA_ANALYSIS.md" << 'DATAANALYSIS_EOF'
# Data Analysis Skills

**Trigger:** ML, statistics, visualization, sklearn, regression, clustering, plots.

## Quick Reference
| Task | Package | Import |
|------|---------|--------|
| ML models | scikit-learn | `from sklearn.ensemble import RandomForestClassifier` |
| Statistics | statsmodels | `import statsmodels.api as sm` |
| Interactive plots | plotly | `import plotly.express as px` |
| Statistical plots | seaborn | `import seaborn as sns` |

## Scikit-learn
```python
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
model = RandomForestClassifier(n_estimators=100)
model.fit(X_train, y_train)
print(classification_report(y_test, model.predict(X_test)))
cv_scores = cross_val_score(model, X, y, cv=5)
```

## Statsmodels
```python
import statsmodels.api as sm
X_const = sm.add_constant(X)
model = sm.OLS(y, X_const).fit()
print(model.summary())  # Full regression output with p-values
```

## Plotly
```python
import plotly.express as px
fig = px.scatter(df, x='x', y='y', color='category', hover_data=['name'])
fig.show()
fig = px.histogram(df, x='value', color='group')
fig = px.box(df, x='category', y='value')
```

## Seaborn
```python
import seaborn as sns
import matplotlib.pyplot as plt
sns.boxplot(data=df, x='category', y='value', hue='group')
sns.heatmap(df.corr(), annot=True, cmap='coolwarm')
sns.pairplot(df, hue='category')
plt.savefig('plot.png', dpi=300)
```

Install: `pip install scikit-learn statsmodels plotly seaborn`
DATAANALYSIS_EOF

    # Create CLINICAL.md
    cat > "${SKILLS_DIR}/scientific/CLINICAL.md" << 'CLINICAL_EOF'
# Clinical Skills

**Trigger:** Clinical trials, PubMed, literature, survival analysis.

## Quick Reference
| Task | Source | Access |
|------|--------|--------|
| Clinical trials | ClinicalTrials.gov | REST API |
| Literature | PubMed | E-utilities |
| Survival analysis | lifelines | Python |

## ClinicalTrials.gov API
```python
import requests
BASE = "https://clinicaltrials.gov/api/v2"
# Search trials
r = requests.get(f"{BASE}/studies", params={
    "query.cond": "breast cancer",
    "query.intr": "pembrolizumab",
    "filter.overallStatus": "RECRUITING"
})
for study in r.json()['studies']:
    info = study['protocolSection']['identificationModule']
    print(f"{info['nctId']}: {info['briefTitle']}")
```

## PubMed
```python
from Bio import Entrez
Entrez.email = "email@example.com"
handle = Entrez.esearch(db="pubmed", term="CRISPR cancer[Title/Abstract]", retmax=20)
pmids = Entrez.read(handle)['IdList']
handle = Entrez.efetch(db="pubmed", id=pmids, rettype="abstract")
print(handle.read())
```

## Survival Analysis (lifelines)
```python
from lifelines import KaplanMeierFitter, CoxPHFitter
from lifelines.statistics import logrank_test

kmf = KaplanMeierFitter()
kmf.fit(durations, events, label='Survival')
kmf.plot_survival_function()

# Compare groups
results = logrank_test(dur1, dur2, ev1, ev2)
print(f"p-value: {results.p_value:.4f}")

# Cox regression
cph = CoxPHFitter()
cph.fit(df, duration_col='time', event_col='event')
cph.print_summary()
```

Install: `pip install biopython requests lifelines`
CLINICAL_EOF

    # AWS-specific skill overrides — overwrite only the platform-sensitive skills.
    # GCP skills written above are left untouched for GCP workspaces.
    if [ "$cloud_platform" = "AWS" ]; then
        log_info "Applying AWS skill variants for WORKFLOW_TROUBLESHOOT and DASHBOARD_BUILDER..."

        cat > "${SKILLS_DIR}/WORKFLOW_TROUBLESHOOT.md" << 'AWS_WORKFLOW_SKILL_EOF'
# WDL Workflow Troubleshooting Skill (AWS)

**Trigger:** User asks to troubleshoot, debug, or fix a failed workflow.

## Behavior

Once the target job is identified:
1. Run all diagnostic commands (Steps 2–4) without waiting for further instruction
2. Collect error message, failed task name, logs, and exit code
3. Identify the root cause from the evidence
4. Present the diagnosis with supporting log snippets or error output
5. Propose a specific fix

---

## Quick Diagnosis (Start Here)

```bash
# 1. Find failed jobs
wb workflow job list --format=json | jq -r '.[] | select(.status=="FAILED") | "\(.id)\t\(.workflowName)\t\(.startTime)"'

# 2. Get error message (replace JOB_ID)
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage // "No message"'

# 3. Find failed task
wb workflow job task list --job=<JOB_ID> --format=json | jq -r '.[] | select(.status=="FAILED") | .name'

# 4. Get task error + logs
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json | jq '{stderr, stdout, exitCode, failureMessage}'
```

**After running these 4 commands, you'll know:** which job failed, why, which task, and where logs are.

---

## Step-by-Step Guide

### Step 1: Identify Failed Job

```bash
wb workflow job list --format=json | jq '.[] | select(.status == "FAILED") | {id, workflowName, status, startTime, endTime}'
```

**For batch jobs:**
```bash
wb workflow job batch list --job=<JOB_ID> --format=json | jq '.[] | select(.status == "FAILED") | {id, status}'
```

**Ask user:** Confirm which job ID to investigate (if multiple failed jobs).

---

### Step 2: Get Job Details & Inputs

```bash
wb workflow job describe --job=<JOB_ID> --format=json
```

**Key fields to extract:**
```bash
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage'
wb workflow job describe --job=<JOB_ID> --format=json | jq '.inputs'
wb workflow job describe --job=<JOB_ID> --format=json | jq '.outputs'
```

---

### Step 3: Find Failed Task & Get Logs

```bash
wb workflow job task list --job=<JOB_ID> --format=json | jq '.[] | {name, status, exitCode}'
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json
```

**Extract log URLs:**
```bash
TASK_INFO=$(wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json)
STDERR_URL=$(echo $TASK_INFO | jq -r '.stderr')
STDOUT_URL=$(echo $TASK_INFO | jq -r '.stdout')
echo "stderr: $STDERR_URL"
echo "stdout: $STDOUT_URL"
```

---

### Step 4: Pull and Analyze Task Logs

#### Read Log Contents

```bash
# Read stderr (usually contains errors) — logs are in S3
aws s3 cp "$STDERR_URL" - 2>/dev/null | tail -100

# Read stdout
aws s3 cp "$STDOUT_URL" - 2>/dev/null | tail -100

# Search for common error patterns
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "error|exception|failed|denied|killed|oom|memory|disk|timeout" | head -30
```

#### Common Log File Patterns

Cromwell execution logs are typically at:
```
s3://<execution-bucket>/<workflow-id>/<call-name>/execution/
├── stdout          # Task standard output
├── stderr          # Task standard error
├── script          # The actual command that ran
├── rc              # Return code (exit code)
└── script.submit   # Submission script
```

**One-liner to read all execution files:**
```bash
EXEC_DIR=$(echo $TASK_INFO | jq -r '.executionDirectory // empty')
if [ -n "$EXEC_DIR" ]; then
  echo "=== script ===" && aws s3 cp "$EXEC_DIR/script" - 2>/dev/null
  echo "=== rc ===" && aws s3 cp "$EXEC_DIR/rc" - 2>/dev/null
  echo "=== stderr (last 50 lines) ===" && aws s3 cp "$EXEC_DIR/stderr" - 2>/dev/null | tail -50
fi
```

---

### Step 5: Check Resource Allocation & Usage

#### What Was Requested (from WDL runtime)

```bash
wb workflow describe --workflow=<WORKFLOW_ID> --format=json | jq '.sourceUrl'

# Read WDL file
aws s3 cp s3://<bucket>/<path>/workflow.wdl - | grep -A10 "runtime {"
```

#### Check Actual Resource Usage (AWS Batch)

```bash
# List failed AWS Batch jobs
aws batch list-jobs --job-queue <QUEUE_NAME> --job-status FAILED \
  --query 'jobSummaryList[*].{id:jobId,name:jobName,status:status}' --output table

# Describe specific batch job
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0] | {
  status: .status,
  statusReason: .statusReason,
  container: .container.resourceRequirements
}'
```

#### Memory-Specific Checks

```bash
# Check if OOM killed the task
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "oom|out of memory|killed|cannot allocate|memory"

# Check what memory was requested in the batch job
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].container.resourceRequirements[] | select(.type=="MEMORY")'

# Check for OOM kill signal in stderr
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i "killed process"
```

---

### Step 6: Diagnose by Error Type

#### Memory Issues (OOM)

**Symptoms:**
- Exit code 137 (SIGKILL) or 143
- "Killed" in stderr
- "Cannot allocate memory"
- Task succeeded locally but fails at scale

**Diagnosis:**
```bash
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].container.resourceRequirements'
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "memory|oom|killed|malloc"
```

**Fix:** Increase `memory` in WDL runtime block:
```wdl
runtime {
  memory: "32G"
}
```

#### Disk Issues

**Symptoms:**
- "No space left on device"
- "Disk quota exceeded"

**Diagnosis:**
```bash
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "space|disk|quota"
```

**Fix:** Increase disk in WDL runtime:
```wdl
runtime {
  disks: "local-disk 200 SSD"
}
```

#### Input File Issues

**Symptoms:**
- "FileNotFoundException"
- "Localization failed"
- File not found errors

**Diagnosis:**
```bash
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.inputs | to_entries[] | .value' | while read path; do
  if [[ $path == s3://* ]]; then
    echo -n "$path: " && aws s3 ls "$path" 2>&1 | head -1
  fi
done
```

#### Permission Issues

**Symptoms:**
- "Permission denied" / "Access denied" / 403 errors

**Diagnosis:**
```bash
# Check IAM role attached to batch job
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].jobDefinition'

# Test bucket access
aws s3 ls s3://<bucket>/ 2>&1 | head -5
```

---

### Step 7: Propose Solution

| Issue | Solution Template |
|-------|-------------------|
| **OOM** | "Increase memory from X to Y in the runtime block" |
| **Disk full** | "Increase disk size from X to Y GB" |
| **Missing input** | "Input file doesn't exist. Verify path: `aws s3 ls <path>`" |
| **Permission** | "IAM role lacks S3 access. Grant `s3:GetObject` on the bucket" |
| **Timeout** | "Task exceeded time limit. Increase `maxRetries` or optimize task" |
| **Docker** | "Image pull failed. Verify image exists and is accessible" |
| **Other** | Describe the root cause from logs and propose a fix based on the specific error |

**Re-run after fixing:**
```bash
wb workflow job run --workflow=<WORKFLOW_ID> --inputs=<INPUTS_JSON>
```

---

## Quick Reference

### Essential Commands

```bash
# Failed jobs
wb workflow job list --format=json | jq '.[] | select(.status=="FAILED") | {id, workflowName}'

# Job error
wb workflow job describe --job=<ID> --format=json | jq '.failureMessage'

# Failed tasks
wb workflow job task list --job=<ID> --format=json | jq '.[] | select(.status=="FAILED") | .name'

# Task logs (S3)
wb workflow job task describe --job=<ID> --task=<TASK> --format=json | jq -r '.stderr' | xargs -I{} aws s3 cp {} - | tail -50

# Memory check (AWS Batch)
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].container.resourceRequirements'
```

### Error → Cause → Fix

| Exit Code | Meaning | Common Fix |
|-----------|---------|------------|
| 1 | General error | Check stderr for details |
| 2 | Misuse of command | Check script syntax |
| 126 | Permission problem | Check file permissions |
| 127 | Command not found | Check PATH, container image |
| 137 | SIGKILL (OOM) | **Increase memory** |
| 139 | Segfault | Check input data, memory |
| 143 | SIGTERM | Task timeout or preemption |

---

## Workbench-Specific Notes

- **Log retention:** Cromwell logs persist in workspace execution bucket (S3)
- **Batch jobs:** Each sub-job has independent logs; troubleshoot specific failed sub-job
- **Preemption:** If using spot instances, set `preemptible: 0` for reliability
AWS_WORKFLOW_SKILL_EOF

        cat > "${SKILLS_DIR}/DASHBOARD_BUILDER.md" << 'AWS_DASHBOARD_SKILL_EOF'
# Web Apps & Dashboards Skill (AWS)

**Build interactive web apps, dashboards, and visualizations that run on a port in Workbench.**

> **Triggers:**
> - "Create a dashboard", "visualize data", "build charts"
> - "Run a Flask/Streamlit/FastAPI app"
> - "Display data in the browser", "interactive UI"
> - Any web app that serves content on a port

---

## 🌐 Workbench Proxy & Web Apps Best Practices

### Proxy URL Format

All web apps in Workbench are accessed via:
```
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
```

### ⚠️ How to Get the App UUID (CRITICAL)

**You MUST automatically get the app UUID - NEVER ask the user for it.**

```bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```

**⚡ LLM INSTRUCTION:** When constructing dashboard/proxy URLs:
1. First run the command above to get the running app UUID
2. Use that actual UUID in the URL you provide
3. Do NOT use placeholders like `[APP_UUID]` in your final response
4. Do NOT ask the user to find/replace the UUID themselves

### ✅ Correct URL Examples
```
https://workbench.verily.com/app/abc123-def456-789/proxy/8080/
https://workbench.verily.com/app/abc123-def456-789/proxy/8501/index.html
```

### ❌ WRONG URL Formats (These WILL fail)
```
https://abc123-def456.workbench-app.verily.com/  ← WRONG
http://localhost:8080/                            ← WRONG: Not accessible externally
```

### ⚠️ Common Issue: JavaScript API Calls Failing

**Problem:** JavaScript using absolute paths fails through Workbench proxy

**Solution: Use Relative Paths (TESTED & CONFIRMED)**

```javascript
// ✅ CORRECT - relative paths work through proxy
fetch('api/metadata')
fetch('api/data?filter=value')

// ❌ WRONG - absolute paths fail
fetch('/api/metadata')
fetch('/api/data?filter=value')
```

---

## Workflow

### Step 1: Understand Requirements

Ask the user:
1. **Data source?** S3 file (CSV, Parquet, JSON), Athena query, or local file?
2. **Visualizations?** Charts (bar, line, scatter), tables, filters?
3. **Interactivity?** Static display or dynamic filtering?

### Step 2: Auto-Detect Environment

```bash
APP_UUID=$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)
echo "App UUID: $APP_UUID"
python3 --version
pwd
```

### Step 3: Install Dependencies

```bash
pip install flask flask-cors pandas plotly boto3 psycopg2-binary
```

### Step 4: Create Dashboard Structure

```
dashboard/
├── app.py
├── templates/
│   └── index.html
└── static/
    └── style.css
```

---

## Working Templates

### Template 1: S3 Data Dashboard

**app.py:**
```python
from flask import Flask, render_template, jsonify
from flask_cors import CORS
import pandas as pd
import boto3
import os

app = Flask(__name__)
CORS(app)

_data_cache = None

def get_data_from_s3():
    global _data_cache
    if _data_cache is not None:
        return _data_cache

    # Use the WORKBENCH_<resource_name> env var set by Workbench
    bucket = os.environ.get('WORKBENCH_my_bucket', 'your-bucket-name')
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=bucket, Key='path/to/data.csv')
    df = pd.read_csv(obj['Body'])
    _data_cache = df.to_dict(orient='records')
    return _data_cache

@app.route('/')
def index():
    return render_template('index.html')

@app.route('api/data')  # NO leading slash!
def get_data():
    try:
        data = get_data_from_s3()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('api/metadata')
def get_metadata():
    try:
        data = get_data_from_s3()
        if data:
            return jsonify({"columns": list(data[0].keys()), "row_count": len(data)})
        return jsonify({"columns": [], "row_count": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # CRITICAL: host='0.0.0.0' required for Workbench proxy access
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

### Template 2: Aurora PostgreSQL Dashboard

```python
import psycopg2
import pandas as pd
import os

def get_data_from_aurora():
    global _data_cache
    if _data_cache is not None:
        return _data_cache

    # WORKBENCH_<resource_name> contains "host:port/dbname" — use wb to get credentials:
    #   wb resource resolve aurora-database --id=<resource-id>
    # Or hard-code connection details after running the above command once.
    conn_ref = os.environ.get('WORKBENCH_my_aurora_db', '').split('/')
    host_port = conn_ref[0].split(':') if conn_ref[0] else ['your-aurora-endpoint', '5432']
    host = host_port[0]
    port = host_port[1] if len(host_port) > 1 else '5432'
    dbname = conn_ref[1] if len(conn_ref) > 1 else 'your-db-name'

    conn = psycopg2.connect(
        host=host, port=port, dbname=dbname,
        user='your-user', password='your-password'
    )
    df = pd.read_sql('SELECT * FROM your_table LIMIT 1000', conn)
    conn.close()
    _data_cache = df.to_dict(orient='records')
    return _data_cache
```

> **Tip:** Use `wb resource resolve aurora-database --id=<id>` to get the connection string, or check the `WORKBENCH_*` env vars populated by Workbench context generation.

### Alternative: Embed Data in HTML (For Static Dashboards)

```python
import json
@app.route('/')
def index():
    data = get_data_from_s3()
    return render_template('dashboard.html', data_json=json.dumps(data))
```

```html
<script>
const data = {{ data_json|safe }};
renderChart(data);
</script>
```

---

## Troubleshooting

### No data showing

**1. Test API directly:**
```bash
curl http://localhost:8080/api/data | python3 -m json.tool | head -20
```

**2. Check S3 access:**
```bash
aws s3 ls s3://<bucket>/path/to/data.csv
```

**3. Check server logs:**
```bash
tail -f server.log
```

### Server won't start

```bash
lsof -i :8080
kill $(lsof -t -i :8080)
python3 app.py
```

### S3 / AWS errors

```bash
# Check AWS credentials
aws sts get-caller-identity

# Test S3 access
aws s3 ls s3://<bucket>/

# Check env vars set by Workbench
env | grep WORKBENCH
```

### Aurora connection errors

```bash
# Get connection string from wb CLI
wb resource resolve aurora-database --id=<resource-id>

# Test connectivity
psql "host=<endpoint> port=5432 dbname=<db> user=<user>"
```

### Server not accessible through proxy

**Fix:** Ensure Flask is bound to `0.0.0.0`, not `localhost`:
```python
app.run(host='0.0.0.0', port=8080)
```

---

## Common Pitfalls Checklist

- [ ] **Relative paths** - All `fetch()` calls use `'api/...'` not `'/api/...'`
- [ ] **Host is 0.0.0.0** - Not `localhost` or `127.0.0.1`
- [ ] **threaded=True** - For concurrent users
- [ ] **debug=False** - For security
- [ ] **App UUID obtained** - Not using placeholder `[APP_UUID]`
- [ ] **S3 access verified** - `aws s3 ls s3://<bucket>/` returns files
- [ ] **Data cached** - Avoid repeated S3 reads
- [ ] **Error handling** - API returns errors as JSON, not crashes
- [ ] **CORS enabled** - `CORS(app)` added

---

## Quick Reference

| Issue | Check | Fix |
|-------|-------|-----|
| 404 on API | Path format | Remove leading `/` from fetch |
| CORS error | CORS setup | Add `CORS(app)` |
| Blank page | Server running? | `ps aux | grep python` |
| S3 error | AWS credentials | `aws sts get-caller-identity` |
| Wrong port | URL vs code | Match port in URL to `app.run()` |
| Works locally, fails via URL | Host binding | Change `localhost` to `0.0.0.0` |
| Gateway timeout | Server/UUID | Check server running + correct UUID |

---

## Example Prompts This Skill Handles

- "Create a dashboard showing data from my S3 bucket"
- "Build an interactive chart for analyzing patient demographics"
- "Visualize the CSV files in my bucket"
- "Make a web dashboard with filters for exploring data"
- "Display query results in a browser with charts"
AWS_DASHBOARD_SKILL_EOF

        log_info "AWS skill variants applied."
    fi
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
    # Two-step declaration so failures fall back to '{}' rather than propagating
    local resource_paths
    resource_paths=$(echo "$resources" | jq -c '
        map(
            {
                key: .id,
                value: (
                    if .resourceType == "GCS_BUCKET" then "gs://\(.bucketName)"
                    elif .resourceType == "AWS_S3_STORAGE_FOLDER" then "s3://\(.bucketName // "unknown")/\(.prefix // "")"
                    elif .resourceType == "AWS_AURORA_DATABASE" then "\(.rwEndpoint // "unknown"):\(.port // "5432")/\(.databaseName // "")"
                    elif .resourceType == "BQ_DATASET" then "\(.projectId).\(.datasetId)"
                    elif .resourceType == "BQ_TABLE" then "\(.projectId).\(.datasetId).\(.tableId // "")"
                    elif .resourceType == "GIT_REPO" then .gitRepoUrl
                    elif .resourceType == "GCS_OBJECT" then "gs://\(.bucketName)/\(.objectName // "")"
                    else null
                    end
                )
            }
        ) | map(select(.value != null)) | from_entries
    ') || resource_paths='{}'
    
    # Generate envVars map: WORKBENCH_<name> -> cloud path
    local env_vars
    env_vars=$(echo "$resources" | jq -c '
        map(
            {
                key: ("WORKBENCH_" + (.id | gsub("-"; "_"))),
                value: (
                    if .resourceType == "GCS_BUCKET" then "gs://\(.bucketName)"
                    elif .resourceType == "AWS_S3_STORAGE_FOLDER" then "s3://\(.bucketName // "unknown")/\(.prefix // "")"
                    elif .resourceType == "AWS_AURORA_DATABASE" then "\(.rwEndpoint // "unknown"):\(.port // "5432")/\(.databaseName // "")"
                    elif .resourceType == "BQ_DATASET" then "\(.projectId).\(.datasetId)"
                    elif .resourceType == "BQ_TABLE" then "\(.projectId).\(.datasetId).\(.tableId // "")"
                    elif .resourceType == "GIT_REPO" then .gitRepoUrl
                    elif .resourceType == "GCS_OBJECT" then "gs://\(.bucketName)/\(.objectName // "")"
                    else null
                    end
                )
            }
        ) | map(select(.value != null)) | from_entries
    ') || env_vars='{}'
    
    # Validate each value is parseable JSON before passing to --argjson.
    # jq-produced output should always be valid, but a corrupt $resources string
    # can leave these as empty or multi-line values that --argjson rejects.
    resource_paths="${resource_paths:-{}}"
    env_vars="${env_vars:-{}}"
    if ! printf '%s' "$resource_paths" | jq empty 2>/dev/null; then
        log_error "resource_paths is not valid JSON (value: ${resource_paths:0:120}); falling back to {}" >&2
        resource_paths='{}'
    fi
    if ! printf '%s' "$env_vars" | jq empty 2>/dev/null; then
        log_error "env_vars is not valid JSON (value: ${env_vars:0:120}); falling back to {}" >&2
        env_vars='{}'
    fi
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
    local cloud_platform="${2:-GCP}"

    if [ "$cloud_platform" = "AWS" ]; then
        local buckets=$(echo "$resources" | jq '[.[] | select(.resourceType == "AWS_S3_STORAGE_FOLDER")]' 2>/dev/null || echo "[]")
        local count=$(echo "$buckets" | jq 'length' 2>/dev/null || echo "0")

        if [ "$count" -eq 0 ] || [ "$count" = "0" ]; then
            echo "*No S3 buckets in this workspace.* Create one with:"
            echo '```bash'
            echo 'wb resource create s3-storage-folder --name my-storage --description "Storage for results"'
            echo '```'
            return
        fi

        echo "| Bucket Name | Resource ID | Description |"
        echo "|-------------|-------------|-------------|"
        echo "$buckets" | jq -r '.[] | "| `s3://\(.bucketName // "unknown")/\(.prefix // "")` | `\(.id // "—")` | \(.description // "—" | if . == "" then "—" else . end) |"' 2>/dev/null || true
    else
        # GCP
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
    fi
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
    
    # Set platform-specific template content (generator branches; output file is clean, no conditionals)
    local storage_bucket_type storage_save_cmd resource_table_rows
    local mcp_data_resources_rows cloud_cli_section cloud_path_hint env_var_example
    local data_preview_query_section create_resources_section
    if [ "$ws_cloud" = "AWS" ]; then
        storage_bucket_type="S3 bucket"
        storage_save_cmd='aws s3 cp <file> s3://<bucket>/'
        resource_table_rows='| `AWS_S3_STORAGE_FOLDER` | AWS S3 storage folder | `wb resource create s3-storage-folder` |
| `AWS_AURORA_DATABASE` | Aurora PostgreSQL database | `wb resource create aurora-database` |
| `AWS_AURORA_DATABASE_REFERENCE` | Aurora DB reference (external) | `wb resource add-ref aurora-database` |
| `GIT_REPO` | Git repository reference | `wb resource add-ref git-repo` |'

        mcp_data_resources_rows='| `workspace_list_data_collections` | N/A | **List data collections and their resources** |
| `workspace_list_resources` | `wb resource list` | List all resources in the workspace |
| `resource_list_tree` | `wb resource list-tree` | List resources organized by folder |
| `list_files` | `aws s3 ls` | List files in an S3 storage folder |
| `read_file` | `aws s3 cp <key> -` | Read contents of a file from S3 |
| `resource_create_bucket` | `wb resource create s3-storage-folder` | Create a new S3 storage folder |
| `resource_delete` | `wb resource delete` | Delete a resource |
| `resource_check_access` | — | Check if IAM role has access to a resource |'

        cloud_cli_section='### Cloud CLIs

No direct AWS CLI MCP wrapper — use `aws` CLI commands in the terminal:
- **S3**: `aws s3 ls s3://<bucket>/`, `aws s3 cp <src> <dst>`
- **Batch**: `aws batch list-jobs --job-queue <queue> --job-status FAILED`
- **Aurora**: `psql "host=<endpoint> port=5432 dbname=<db> user=<user>"`'

        cloud_path_hint='# Look for: bucketName+prefix (S3), rwEndpoint+port+databaseName (Aurora), gitRepoUrl'

        env_var_example='echo $WORKBENCH_my_bucket      # → s3://bucket/prefix
env | grep WORKBENCH_           # List all'

        data_preview_query_section='**S3:**
```bash
aws s3 ls s3://<bucket>/<prefix>/
aws s3 cp s3://<bucket>/<prefix>/file.csv - | head -20
```

**Aurora PostgreSQL:**
```bash
# Get endpoint from wb CLI
wb resource describe <resource-name> --format=json | jq .rwEndpoint
# Connect
psql "host=<rwEndpoint> port=<port> dbname=<databaseName> user=<user>"
# \dt  →  list tables;  SELECT * FROM table_name LIMIT 10;
```

### Query Data

**Python:**
```python
import boto3, pandas as pd

# Read CSV from S3
s3 = boto3.client("s3")
obj = s3.get_object(Bucket="<bucket>", Key="<prefix>/file.csv")
df = pd.read_csv(obj["Body"])

# Read Parquet directly (requires s3fs)
df = pd.read_parquet("s3://<bucket>/<prefix>/file.parquet")

# Aurora PostgreSQL
import psycopg2
conn = psycopg2.connect(host="<rwEndpoint>", port=<port>, dbname="<db>", user="<user>", password="<pass>")
df = pd.read_sql("SELECT * FROM table_name LIMIT 100", conn)
conn.close()
```'

        create_resources_section='```bash
# S3 storage folder
wb resource create s3-storage-folder --name my-storage --description "My storage folder"

# Aurora PostgreSQL database
wb resource create aurora-database --name my-db --description "My database"

# Reference an external Aurora database
wb resource add-ref aurora-database --name external-db
```'

    else
        storage_bucket_type="GCS bucket"
        storage_save_cmd='gsutil cp <file> gs://<bucket>/'
        resource_table_rows='| `GCS_BUCKET` | Google Cloud Storage bucket | `wb resource create gcs-bucket` |
| `BQ_DATASET` | BigQuery dataset | `wb resource create bq-dataset` |
| `GIT_REPO` | Git repository reference | `wb resource add-ref git-repo` |
| `GCS_OBJECT` | Individual GCS file reference | `wb resource add-ref gcs-object` |
| `BQ_TABLE` | BigQuery table reference | `wb resource add-ref bq-table` |'

        mcp_data_resources_rows='| `workspace_list_data_collections` | N/A | **List data collections and their resources** |
| `workspace_list_resources` | `wb resource list` | List all resources in the workspace |
| `resource_list_tree` | `wb resource list-tree` | List resources organized by folder |
| `bq_execute` | `bq query` | Run SQL queries against BigQuery |
| `list_files` | `gsutil ls` | List files in a GCS bucket |
| `read_file` | `gsutil cat` | Read contents of a file |
| `resource_create_bucket` | `wb resource create gcs-bucket` | Create a new GCS bucket |
| `resource_delete` | `wb resource delete` | Delete a resource |
| `resource_check_access` | — | Check if service account has access to a resource |
| `resource_mount` / `resource_unmount` | — | Mount/unmount a GCS bucket |'

        cloud_cli_section='### Cloud CLIs (via MCP)

| MCP Tool | Description |
|----------|-------------|
| `gcloud_execute` | Run any `gcloud` command |
| `gsutil_execute` | Run any `gsutil` command |
| `bq_execute` | Run any `bq` SQL query |'

        cloud_path_hint='# Look for: bucketName, projectId+datasetId, gitRepoUrl'

        env_var_example='echo $WORKBENCH_my_bucket      # → gs://actual-bucket-name
env | grep WORKBENCH_           # List all'

        data_preview_query_section='**BigQuery:**
```bash
bq head -n 10 <project>:<dataset>.<table>
bq show --schema <project>:<dataset>.<table>
bq query --use_legacy_sql=false '"'"'SELECT * FROM `project.dataset.table` LIMIT 10'"'"'
```

**GCS:**
```bash
gsutil ls gs://<bucket>/
gsutil cat -r 0-1024 gs://<bucket>/path/file.csv
```

### Query Data

**CLI:**
```bash
bq query --use_legacy_sql=false '"'"'SELECT col1, col2 FROM `project.dataset.table` LIMIT 100'"'"'
```

**Python:**
```python
from google.cloud import bigquery
client = bigquery.Client()
df = client.query("SELECT * FROM `project.dataset.table` LIMIT 100").to_dataframe()

import pandas as pd
df = pd.read_parquet("gs://bucket-name/path/file.parquet")
```'

        create_resources_section='```bash
# GCS bucket
wb resource create gcs-bucket --name my-bucket --description "My bucket"

# BigQuery dataset
wb resource create bq-dataset --name my-dataset --description "My dataset"

# Reference external GCS bucket
wb resource add-ref gcs-bucket --name external-data --bucket-name existing-bucket
```'
    fi

    # Generate dynamic sections
    local embedded_json=$(generate_embedded_json "$resources")
    local bucket_list=$(generate_bucket_list "$resources" "$ws_cloud")
    
    # Write the file
    cat > "${CLAUDE_FILE}" << EOF
# Workbench Context

You are working inside **Verily Workbench**, a secure cloud-based research environment for biomedical data analysis.

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
${resource_table_rows}

**Environment Variables**: Each resource is available as \`\$WORKBENCH_<resource_name>\` (e.g., \`\$WORKBENCH_my_bucket\`).

### Data Collections
Curated datasets published to the Workbench catalog. When added to a workspace, their resources are cloned as **folders** — they may look like user-created resources but originated externally. Common types include clinical data (OMOP, FHIR), genomics (VCF, BAM), and wearables.

Data collections can carry **policies** that restrict how their data is used (region, export controls, access groups).

**To identify resources from data collections:**
1. Use \`workspace_list_data_collections\` — groups resources by source collection (preferred)
2. Or use \`workspace_list_resources\` with \`workspaceId\` — returns full resource metadata including \`resourceLineage\`, which contains the source collection ID and original resource ID

### Workflows
Workflows are reproducible pipelines in WDL or Nextflow format, registered in the workspace.

### Policies & Constraints
Workspaces may have policies that restrict:
- **Region**: Where data and compute must reside
- **Groups**: Who can access the workspace
- **Export**: Whether data can leave the workspace

Check with: \`wb workspace describe\`

---

## ⚠️ Important: Data Persistence

Local app storage is ephemeral — files saved to the app's local disk are **lost when the app stops or restarts**. Always encourage users to save important work to a ${storage_bucket_type} in their workspace.

- **When users create files locally**, suggest saving to a bucket: \`${storage_save_cmd}\`
- **When users finish analysis**, remind: *"Save important outputs to cloud storage before stopping the app."*
- **Available buckets in this workspace:**

${bucket_list}

---

## Most Commonly Used MCP Tools

> **Always use MCP tools before falling back to CLI. MCP tools return structured JSON and are faster.**

| Interface | Best For |
|-----------|----------|
| **MCP Tools** | List/query operations — structured responses, no shell needed |
| **CLI (\`wb\`)** | Complex operations or anything not covered by MCP |

### Data & Resources

| MCP Tool | CLI Equivalent | Description |
|----------|----------------|-------------|
${mcp_data_resources_rows}

### Apps & Workflows

| MCP Tool | CLI Equivalent | Description |
|----------|----------------|-------------|
| \`app_list\` | \`wb app list\` | List running apps |
| \`app_create\` | \`wb app create\` | Create a new custom app |
| \`app_get_url\` | — | Get the proxy URL for a running app |
| \`app_start\` / \`app_stop\` | \`wb app start/stop\` | Start or stop an app |
| \`workflow_list\` | \`wb workflow list\` | List available workflows |
| \`workflow_job_run\` | \`wb workflow run\` | Submit a WDL/Nextflow workflow |
| \`workflow_job_list\` | \`wb workflow job list\` | List workflow job runs |
| \`workflow_job_describe\` | \`wb workflow job describe\` | Get details of a specific job run |
| \`workflow_job_cancel\` | \`wb workflow job cancel\` | Cancel a running job |
| \`get_workflow_status\` | \`wb workflow describe\` | Check status of a workflow run |

### Data Explorer

| MCP Tool | Description |
|----------|-------------|
| \`underlay_list\` | List available data underlays (datasets in the Data Explorer catalog) |
| \`underlay_get_schema\` | Get the schema for a specific underlay |
| \`underlay_list_entities\` | List entity types in an underlay (e.g. person, condition) |
| \`data_sample_instances\` | Sample rows from an entity within a cohort |
| \`data_query_hints\` | Get value hints for filtering an entity attribute |
| \`study_list\` | List studies available in Data Explorer |
| \`study_list_cohorts\` | List cohorts within a study |
| \`cohort_create_in_workspace\` | Create a cohort in the workspace |
| \`cohort_count_instances\` | Count members in a cohort |
| \`export_cohort\` | Export cohort data to a bucket |

${cloud_cli_section}

**Not available via MCP (use CLI):** \`wb workspace set\`, \`wb auth login\`, \`wb workflow logs\`

## CLI Quick Reference

\`\`\`bash
# Workspace
wb workspace describe          # Current workspace details
wb workspace list              # All your workspaces
wb workspace set <id>          # Switch workspace

# Resources
wb resource list               # List resources
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

# Auth
wb auth status                 # Check authentication
wb auth login                  # Re-authenticate
\`\`\`

---

## Data Discovery & Querying

> **⚡ MCP FIRST:** Always check if an MCP tool exists before using CLI commands.

### Find Your Resources

**Use MCP tools (preferred):**
| What You Need | MCP Tool |
|---------------|----------|
| Data collections + their resources | \`workspace_list_data_collections\` |
| All resources (flat list) | \`workspace_list_resources\` |
| Resources organized by folder | \`resource_list_tree\` |

**CLI fallback:**
\`\`\`bash
wb resource list --format=json | jq '.[] | {name: .id, type: .resourceType}'
\`\`\`

### Get the Cloud Path for a Resource

\`\`\`bash
wb resource describe <resource-name> --format=json
${cloud_path_hint}
\`\`\`

### Use Environment Variables (Easiest)

\`\`\`bash
${env_var_example}
\`\`\`

### Preview Data

${data_preview_query_section}

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

${create_resources_section}

---

## ⚠️ Workbench Web Apps & Proxy URLs

> **🚨 If the user wants a dashboard, chart, Flask app, HTML page, or ANY web UI — read \`~/.claude/skills/DASHBOARD_BUILDER.md\` first.**

### Proxy URL Format

The proxy URL is the **only valid way** to access web apps in Workbench:
\`\`\`
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
\`\`\`

Retrieve the App UUID automatically:
\`\`\`bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
\`\`\`

### Common Ports

| Content Type | Port |
|--------------|------|
| Flask/FastAPI | 8080 |
| Streamlit | 8501 |
| Static HTML | 8000 |
| R Shiny | 3838 |

### ⚠️ JavaScript: Always Use Relative Paths

All \`fetch()\` calls in JavaScript **must** use relative paths (no leading \`/\`):

\`\`\`javascript
fetch('api/data')   // ✅ resolves to workbench.verily.com/app/UUID/proxy/8080/api/data
fetch('/api/data')  // ❌ resolves to workbench.verily.com/api/data — 404!
\`\`\`

### ❌ Wrong URL Formats

\`\`\`
https://UUID.workbench-app.verily.com/   ← Bad Request error
http://localhost:8080/                   ← Not accessible externally
file:///home/jupyter/dashboard.html      ← JavaScript blocked
\`\`\`

---

## Available Skills

### Workbench Skills

Read these directly — no index needed:

| Topic | Skill File | When to Use |
|-------|------------|-------------|
| **🚨 Dashboards, Web UIs** | \`DASHBOARD_BUILDER.md\` | Dashboard, Flask, Streamlit, web UI, plots on a port |
| Building custom apps | \`CUSTOM_APP.md\` | Deployable Workbench apps |
| App templates | \`APP_TEMPLATES.md\` | Pre-built templates for dashboards, APIs, file processors |
| **Workflow debugging** | \`WORKFLOW_TROUBLESHOOT.md\` | Failed WDL/Nextflow, logs, memory/disk issues |

### Scientific Skills

> **📚 Read \`~/.claude/skills/SCIENTIFIC_SKILLS_INDEX.md\` first** to navigate scientific domain skills.

| Domain | Skill File | Covers |
|--------|------------|--------|
| 🧬 Bioinformatics | \`scientific/BIOINFORMATICS.md\` | scanpy, anndata, pydeseq2, biopython, scvelo |
| 💊 Drug Discovery | \`scientific/DRUG_DISCOVERY.md\` | rdkit, deepchem, chembl, drugbank, opentargets |
| 🔬 Genomics DBs | \`scientific/GENOMICS_DATABASES.md\` | ensembl, uniprot, clinvar, pdb |
| 📊 Data Analysis | \`scientific/DATA_ANALYSIS.md\` | sklearn, statsmodels, plotly, seaborn |
| 🏥 Clinical | \`scientific/CLINICAL.md\` | clinicaltrials.gov, pubmed, lifelines |

### ⚡ Skill Trigger Guide

**ALWAYS read \`DASHBOARD_BUILDER.md\` FIRST when user says ANY of these:**
- "create a dashboard"
- "visualize data" / "show me a chart" / "display data"
- "build a Flask app" / "run Flask" / "Flask server"
- "Streamlit" / "Plotly" / "interactive chart"
- "run on port" / "serve HTML" / "web page"
- "show in browser" / "open in new tab"
- Any request to display data interactively

**Read \`CUSTOM_APP.md\` when:**
- "build a deployable app" / "create a custom app"
- "API service" / "backend" / "from scratch"

**Read \`APP_TEMPLATES.md\` when:**
- "dashboard template" / "starter template" / "pre-built app"
- "what templates are available" / "which template should I use"

**Read \`WORKFLOW_TROUBLESHOOT.md\` when:**
- "troubleshoot my workflow" / "fix my workflow"
- "my workflow failed" / "workflow error" / "debug workflow"
- "troubleshoot my job" / "my job failed" / "workflow job failed"
- "job failed" / "task failed" / "out of memory"
- "check logs" / "why did it fail" / "troubleshoot"

**Read \`SCIENTIFIC_SKILLS_INDEX.md\` then the relevant domain file when user mentions:**
- "single-cell" / "RNA-seq" / "scanpy" / "differential expression"
- "molecule" / "SMILES" / "drug" / "RDKit" / "ChEMBL"
- "gene" / "protein" / "variant" / "UniProt" / "Ensembl" / "PDB"
- "machine learning" / "sklearn" / "statistics"
- "clinical trial" / "PubMed" / "survival analysis"

---

## Quick Reference (Machine-Readable)

Use this JSON for exact resource paths and environment variables:

\`\`\`json
${embedded_json}
\`\`\`

**Usage:**
- \`resourcePaths["my-bucket"]\` → exact cloud storage/database path
- \`envVars["WORKBENCH_my_bucket"]\` → environment variable value

To refresh after workspace changes:
\`\`\`bash
~/.claude/generate-context.sh
\`\`\`

---

## Getting Help

- **Docs**: https://support.workbench.verily.com
- **Custom Apps Guide**: https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/
- **Devcontainers Repo**: https://github.com/verily-src/workbench-app-devcontainers
- **Devcontainer Reference**: https://containers.dev/implementors/json_reference/
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

    # Fetch all data first so we can detect cloud platform before generating skills
    WORKSPACE=$(fetch_workspace)
    RESOURCES=$(fetch_resources)
    WORKFLOWS=$(fetch_workflows)
    APPS=$(fetch_apps)

    # Detect cloud platform for platform-specific skill and context generation
    local cloud_platform
    cloud_platform=$(echo "$WORKSPACE" | jq -r '.cloudPlatform // "GCP"')
    log_info "Detected cloud platform: ${cloud_platform}"

    install_skills "$cloud_platform"

    # Generate single CLAUDE.md file with embedded JSON
    generate_claude_md "$WORKSPACE" "$RESOURCES" "$WORKFLOWS" "$APPS"

    echo "" >&2
    log_info "Context generation complete!"
    echo "" >&2
    echo "Generated file:" >&2
    echo "  - ${CLAUDE_FILE}" >&2
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "✅ Claude Code will automatically discover ~/.claude/CLAUDE.md" >&2
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "" >&2
}

# Run main
main "$@"
