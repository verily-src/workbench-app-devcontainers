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

All web apps in Workbench are accessed via:
\`\`\`
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
\`\`\`

### ⚠️ How to Get the App UUID (CRITICAL)

**You MUST automatically get the app UUID - NEVER ask the user for it.**

\`\`\`bash
# Run this command and use the output:
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
\`\`\`

**⚡ LLM INSTRUCTION:** When constructing dashboard/proxy URLs:
1. First run the command above to get the running app UUID
2. Use that actual UUID in the URL you provide
3. Do NOT use placeholders like \`[APP_UUID]\` in your final response
4. Do NOT ask the user to find/replace the UUID themselves

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

### Why Absolute Paths Fail

\`\`\`
User visits: https://workbench.verily.com/app/UUID/proxy/8080/

Absolute path: fetch('/api/data')
  → Browser resolves to: https://workbench.verily.com/api/data ❌ (404!)

Relative path: fetch('api/data')  
  → Browser resolves to: https://workbench.verily.com/app/UUID/proxy/8080/api/data ✅
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

Before deploying any web app:

- [ ] **Relative paths** - All \`fetch()\` calls use \`'api/...'\` not \`'/api/...'\`
- [ ] **Test locally** - \`curl http://localhost:PORT/api/endpoint\` returns data
- [ ] **Server logs** - Verify API requests arrive: \`tail -f server.log\`
- [ ] **Browser DevTools** - Network tab shows 200 status for API calls
- [ ] **App UUID obtained** - Not using placeholder \`[APP_UUID]\`

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

## ⚡ MCP Tools First!

> **Before running ANY CLI command, check if an MCP tool exists for the operation.**
> MCP tools return structured JSON and are faster than parsing CLI output.

| Common Task | ✅ Use This MCP Tool |
|-------------|---------------------|
| List data collections | \`workspace_list_data_collections\` |
| List resources | \`workspace_list_resources\` |
| Resources by folder | \`resource_list_tree\` |
| Query BigQuery | \`bq_execute\` |
| List bucket files | \`list_files\` |

**Skip to:** [Data Exploration Cheatsheet](#-data-exploration-cheatsheet) | [MCP Tools](#mcp-tools-available)

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

1. **Use the MCP \`workspace_list_data_collections\` tool** to get resources grouped by data collection
2. Or use \`workspace_list_resources\` with workspaceId to get full resource metadata
3. The \`resourceLineage\` object contains:
   - \`sourceWorkspaceId\`: UUID of the data collection
   - \`sourceResourceId\`: UUID of the original resource

**Example:** Ask "Use workspace_list_data_collections to show me which data collections my resources came from"

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

> **⚡ MCP FIRST:** Always check if an MCP tool exists before using CLI commands. MCP tools return structured data and are faster.

### Step 1: Find Your Resources

**🎯 Use MCP tools (preferred):**
| What You Need | MCP Tool |
|---------------|----------|
| Data collections + their resources | \`workspace_list_data_collections\` |
| All resources (flat list) | \`workspace_list_resources\` |
| Resources organized by folder | \`resource_list_tree\` |

**CLI fallback:**
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

| User Question | Best Tool | Command/Tool |
|---------------|-----------|--------------|
| "What data collections do I have?" | **MCP** | \`workspace_list_data_collections\` |
| "What resources are in my workspace?" | **MCP** | \`workspace_list_resources\` |
| "Show resources by folder" | **MCP** | \`resource_list_tree\` |
| "Query this BigQuery table" | **MCP** | \`bq_execute\` |
| "What tables are in this dataset?" | CLI | \`bq ls <project>:<dataset>\` |
| "What columns in this table?" | CLI | \`bq show --schema <project>:<dataset>.<table>\` |
| "How big is this table?" | CLI | \`bq show --format=prettyjson ... \\| jq '{rows: .numRows}'\` |
| "Show me sample data" | CLI | \`bq head -n 5 <project>:<dataset>.<table>\` |
| "List files in bucket" | **MCP** | \`list_files\` |

> **⚠️ Pattern to avoid:** Don't default to \`wb resource list\` for data collection questions. Use \`workspace_list_data_collections\` instead!

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

### ⚠️ Common Operations — USE MCP, NOT CLI

These operations have dedicated MCP tools. **Do NOT use CLI for these:**

| Operation | ✅ Use MCP Tool | ❌ Don't Use CLI |
|-----------|-----------------|------------------|
| List data collections | \`workspace_list_data_collections\` | ~~\`wb resource list\`~~ |
| List all resources | \`workspace_list_resources\` | ~~\`wb resource list\`~~ |
| Resources by folder | \`resource_list_tree\` | ~~\`wb resource list-tree\`~~ |
| Run BigQuery query | \`bq_execute\` | ~~\`bq query\`~~ |
| List bucket files | \`list_files\` | ~~\`gsutil ls\`~~ |

### 🤖 LLM Decision Guide

1. **ALWAYS check MCP tools first** — especially for list/query operations
2. **Fall back to CLI only** when MCP doesn't have the tool
3. **Use cloud CLIs** (\`gsutil\`, \`bq\`) only for operations MCP doesn't support

### Example: Same Operation, Two Ways

**List resources:**
- ✅ MCP: Use \`workspace_list_resources\` tool → returns JSON array
- ⚠️ CLI: Run \`wb resource list --format=json\` → requires shell, parsing

**Query BigQuery:**
- ✅ MCP: Use \`bq_execute\` tool with query parameter → returns results
- ⚠️ CLI: Run \`bq query --use_legacy_sql=false 'SELECT ...'\` → requires parsing

---

## MCP Tools Available

The Workbench MCP server exposes these tools for programmatic LLM access:

| MCP Tool | CLI Equivalent | Description |
|----------|----------------|-------------|
| \`workspace_list_data_collections\` | N/A | **List data collections and their resources** |
| \`workspace_list_resources\` | \`wb resource list\` | List all resources in the workspace |
| \`resource_list_tree\` | \`wb resource list-tree\` | List resources organized by folder |
| \`bq_execute\` | \`bq query\` | Run SQL queries against BigQuery |
| \`workflow_job_run\` | \`wb workflow run\` | Submit a WDL/Nextflow workflow |
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

## ⚠️ Workbench Web Apps & Proxy URLs (CRITICAL)

> **🚨 STOP! If user wants a dashboard, chart, Flask app, HTML page, or ANY web UI:**
> **→ READ \`~/.workbench/skills/DASHBOARD_BUILDER.md\` FIRST!**
> 
> That skill contains critical configuration, working templates, and troubleshooting for all interactive web content.

### Quick Reference

**Proxy URL format (all web content):**
\`\`\`
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
\`\`\`

**Get App UUID automatically (NEVER ask user for it):**
\`\`\`bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
\`\`\`

### ⚠️ JavaScript Relative Paths (Critical for Dashboards)

**All fetch() calls in JavaScript MUST use relative paths:**
\`\`\`javascript
// ✅ CORRECT - works through Workbench proxy
fetch('api/data')

// ❌ WRONG - absolute path breaks through proxy (404 error!)
fetch('/api/data')
\`\`\`

**Why:** \`fetch('/api/data')\` resolves to \`workbench.verily.com/api/data\` (wrong!)  
**Should be:** \`workbench.verily.com/app/UUID/proxy/PORT/api/data\`

### Common Ports
| Content Type | Port | Example Command |
|--------------|------|-----------------|
| Flask/FastAPI | 8080 | \`flask run --port 8080\` |
| Streamlit | 8501 | \`streamlit run app.py\` |
| Static HTML | 8000 | \`python3 -m http.server 8000\` |
| R Shiny | 3838 | (configured in app) |

### ❌ Wrong URL Formats
\`\`\`
https://UUID.workbench-app.verily.com/     ← Bad Request error
http://localhost:8080/                     ← Not accessible externally  
file:///home/jupyter/dashboard.html        ← JavaScript blocked
\`\`\`

---

## Creating Custom Apps

> **When a user asks to create an app, turn code into an app, or build something deployable:**

### Step 1: Determine the Type

| User Wants... | Read This Skill |
|---------------|-----------------|
| Dashboard, visualization, Flask app, web UI | \`DASHBOARD_BUILDER.md\` |
| Deployable custom app from scratch | \`CUSTOM_APP.md\` |

### Step 2: Use the Appropriate Skill

**For dashboards/web UIs** → \`~/.workbench/skills/DASHBOARD_BUILDER.md\`
- Working Flask templates with BigQuery
- Critical proxy URL configuration
- Tested troubleshooting guides

**For deployable apps** → \`~/.workbench/skills/CUSTOM_APP.md\`
- Minimal devcontainer pattern
- Docker configuration
- Deployment checklist

### Quick Reference
- **Templates**: https://github.com/aculotti-verily/wb-app-mcp-and-context/tree/templates-only/src/templates/
- **Full-featured apps**: https://github.com/verily-src/workbench-app-devcontainers

---

## Available Skills

When users ask about specific topics, **read these skill files** for detailed guidance:

| Topic | Skill File | When to Use |
|-------|------------|-------------|
| **🚨 Dashboards, HTML, Flask, Web UIs** | \`~/.workbench/skills/DASHBOARD_BUILDER.md\` | **READ THIS FIRST** for any: dashboard, chart, visualization, Flask app, Streamlit, HTML page, web UI, interactive display, Plotly, or anything running on a port |
| Building custom apps | \`~/.workbench/skills/CUSTOM_APP.md\` | User wants to build a deployable app from scratch |

### ⚡ Skill Trigger Guide

**ALWAYS read \`DASHBOARD_BUILDER.md\` FIRST when user says ANY of these:**
- "create a dashboard"
- "visualize data" / "show me a chart" / "display data"
- "build a Flask app" / "run Flask" / "Flask server"
- "Streamlit" / "Plotly" / "interactive chart"
- "run on port" / "serve HTML" / "web page"
- "show in browser" / "open in new tab"
- Any request to display data interactively

**Read CUSTOM_APP.md when:**
- "build a deployable app" / "create a custom app"
- "API service" / "backend" / "from scratch"

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
