# Web Apps & Dashboards Skill

**Build interactive web apps, dashboards, and visualizations that run on a port in Workbench.**

> **Triggers:**
> - "Create a dashboard", "visualize data", "build charts"
> - "Run a Flask/Streamlit/FastAPI app"
> - "Display data in the browser", "interactive UI"
> - Any web app that serves content on a port

---

## Workbench Proxy & Web Apps Best Practices

### Proxy URL Format

All web apps in Workbench are accessed via:
```
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
```

### How to Get the App UUID (CRITICAL)

**You MUST automatically get the app UUID - NEVER ask the user for it.**

**Option A (preferred):** Use MCP tools — no shell needed, no permission prompt:
```
mcp__wb__app_get_url(appId=<app-resource-name>)
```
To find the app resource name, use `mcp__wb__workspace_list_resources` and filter for
EC2 instances (`AWS_EC2_INSTANCE`) or GCE instances owned by the current user.

**Option B:** Use the CLI:
```bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```
Note: this can intermittently return 401 on some workspaces. If it fails, fall back to Option A.

**LLM INSTRUCTION:** When constructing dashboard/proxy URLs:
1. Use one of the methods above to get the running app UUID
2. Use that actual UUID in the URL you provide
3. Do NOT use placeholders like `[APP_UUID]` in your final response
4. Do NOT ask the user to find/replace the UUID themselves

### Correct URL Examples
```
https://workbench.verily.com/app/abc123-def456-789/proxy/8080/
https://workbench.verily.com/app/abc123-def456-789/proxy/8501/index.html
```

### WRONG URL Formats (These WILL fail)
```
https://abc123-def456.workbench-app.verily.com/  <- WRONG: "Bad Request" error
http://localhost:8080/                            <- WRONG: Not accessible externally
file:///home/jupyter/dashboard.html               <- WRONG: JavaScript blocked
```

### Common Issue: JavaScript API Calls Failing

**Problem:** JavaScript using absolute paths fails through Workbench proxy.

Note: This rule applies to **JavaScript `fetch()` calls only**. Flask/FastAPI route
decorators still require a leading slash (e.g., `@app.route('/api/data')`).

```javascript
// CORRECT - relative paths work through proxy
fetch('api/metadata')
fetch('api/data?filter=value')

// WRONG - absolute paths fail through proxy
fetch('/api/metadata')
fetch('/api/data?filter=value')
```

**Why:**
```
Absolute: fetch('/api/data')  -> https://workbench.verily.com/api/data         (404)
Relative: fetch('api/data')   -> https://workbench.verily.com/app/UUID/proxy/8080/api/data  (OK)
```

---

## Workflow

### Step 1: Understand Requirements

Ask the user:
1. **Data source?** Aurora database, S3 file (CSV, Parquet), BigQuery, or local file?
2. **Visualizations?** Charts (bar, line, scatter), tables, filters?
3. **Interactivity?** Static display or dynamic filtering?

### Step 2: Auto-Detect Environment

Get the app UUID using MCP tools (see "How to Get the App UUID" above).
**Prefer MCP tools over `wb app list`** to avoid permission prompts.

### Step 3: Check Dependencies

The following packages are **pre-installed** in the Workbench Jupyter+LLM image:
`fastapi`, `uvicorn`, `flask`, `flask-cors`, `plotly`, `pandas`, `boto3`, `psycopg2-binary`

**Do NOT run `pip install` unless a specific import fails.** To verify:
```bash
python3 -c "import flask; import fastapi; import plotly; print('OK')"
```
Only install if the check above fails.

> **Note (GCP/BigQuery):** If using BigQuery with pandas, also install `db-dtypes` — it is
> required for proper data type conversion and causes cryptic errors if missing:
> `pip install --no-cache-dir db-dtypes`

### Step 4: Create Dashboard Structure

```
dashboard/
├── app.py              # Flask/FastAPI server
├── templates/
│   └── index.html      # Dashboard HTML with Plotly.js
└── static/
    └── style.css       # Optional styling
```

---

## Working Templates

### Template 1: Aurora PostgreSQL Dashboard (AWS)

Aurora in Workbench uses **IAM database authentication** — you cannot connect with a
static password. The correct flow is:

1. Get temporary AWS credentials via `wb resource credentials`
2. Generate an IAM auth token via boto3 (token is valid for 15 minutes)
3. Connect with `sslmode='require'` — **SSL is mandatory**

**Preferred: Use MCP tools for data queries** to avoid the IAM auth complexity entirely:
```
mcp__wb__aurora_query(resourceName="my-db", query="SELECT * FROM table LIMIT 100")
mcp__wb__aurora_list_tables(resourceName="my-db")
mcp__wb__aurora_describe_table(resourceName="my-db", tableName="my_table")
```

Query via MCP, embed results in the template, and serve with Flask/FastAPI.
This avoids IAM auth in the app code entirely.

**If live database queries are needed in the app:**

```python
import json, subprocess, boto3, psycopg2, os

def get_aurora_connection(resource_id, username):
    result = subprocess.run(
        ['wb', 'resource', 'credentials',
         f'--id={resource_id}', '--scope=READ_ONLY', '--format=json'],
        capture_output=True, text=True, check=True
    )
    creds = json.loads(result.stdout)

    conn_str = os.environ.get(f'WORKBENCH_{resource_id.replace("-", "_")}', '')
    host_part, _, dbname = conn_str.partition('/')
    host, _, port = host_part.partition(':')
    port = int(port) if port else 5432

    session = boto3.Session(
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken'],
        region_name='us-west-2'
    )
    token = session.client('rds').generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=username, Region='us-west-2'
    )
    return psycopg2.connect(
        host=host, port=port, database=dbname,
        user=username, password=token,
        sslmode='require'
    )
```

### Template 2: S3 Data Dashboard (AWS)

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
    bucket = os.environ.get('WORKBENCH_my_bucket', 'your-bucket-name')
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=bucket, Key='path/to/data.csv')
    df = pd.read_csv(obj['Body'])
    _data_cache = df.to_dict(orient='records')
    return _data_cache

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    try:
        return jsonify(get_data_from_s3())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

### Template 3: BigQuery Dashboard (GCP)

```python
from flask import Flask, render_template, jsonify, request
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
    query = "SELECT * FROM `project.dataset.table` LIMIT 1000"
    df = client.query(query).to_dataframe()
    _data_cache = df.to_dict(orient='records')
    return _data_cache

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    try:
        data = get_bigquery_data()
        column = request.args.get('filter_column')
        value = request.args.get('filter_value')
        if column and value:
            data = [row for row in data if str(row.get(column, '')) == value]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/metadata')
def get_metadata():
    try:
        data = get_bigquery_data()
        if data:
            return jsonify({"columns": list(data[0].keys()), "row_count": len(data)})
        return jsonify({"columns": [], "row_count": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

> **Note:** Requires `google-cloud-bigquery` and `db-dtypes`. Install with:
> `pip install --no-cache-dir google-cloud-bigquery db-dtypes`

### Alternative: Embed Data in HTML (For Static Dashboards)

Query data via MCP or Python, then embed directly in the template. No API calls needed.

```python
import json
@app.route('/')
def index():
    data = get_data()
    return render_template('dashboard.html', data_json=json.dumps(data))
```

```html
<script>
const data = {{ data_json|safe }};
renderChart(data);
</script>
```

### Dashboard Frontend Template (index.html)

Use this with any backend template above. All `fetch()` calls use **relative paths** (no leading `/`).

```html
<!DOCTYPE html>
<html>
<head>
    <title>Data Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .chart { background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .loading { text-align: center; padding: 40px; color: #666; }
        .error { color: #d32f2f; padding: 20px; background: #ffebee; border-radius: 4px; }
        h1 { color: #333; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Data Dashboard</h1>
        <div id="metadata" class="chart">
            <h3>Dataset Info</h3>
            <div id="metadata-content" class="loading">Loading metadata...</div>
        </div>
        <div id="chart1" class="chart">
            <h3>Data Visualization</h3>
            <div id="chart-content" class="loading">Loading chart...</div>
        </div>
        <div id="table" class="chart">
            <h3>Data Table</h3>
            <div id="table-content" class="loading">Loading data...</div>
        </div>
    </div>

    <script>
        async function loadMetadata() {
            try {
                const response = await fetch('api/metadata');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                document.getElementById('metadata-content').innerHTML = `
                    <p><strong>Columns:</strong> ${data.columns.join(', ')}</p>
                    <p><strong>Rows:</strong> ${data.row_count}</p>
                `;
            } catch (error) {
                document.getElementById('metadata-content').innerHTML =
                    `<div class="error">Error: ${error.message}</div>`;
            }
        }

        async function loadChart() {
            try {
                const response = await fetch('api/data');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                if (data.length === 0) {
                    document.getElementById('chart-content').innerHTML = '<p>No data available</p>';
                    return;
                }
                const columns = Object.keys(data[0]);
                const numericCol = columns.find(col => typeof data[0][col] === 'number') || columns[1];
                const labelCol = columns[0];

                Plotly.newPlot('chart-content', [{
                    x: data.slice(0, 20).map(row => row[labelCol]),
                    y: data.slice(0, 20).map(row => row[numericCol]),
                    type: 'bar',
                    marker: { color: '#1976d2' }
                }], {
                    title: `${numericCol} by ${labelCol}`,
                    xaxis: { title: labelCol },
                    yaxis: { title: numericCol }
                });
            } catch (error) {
                document.getElementById('chart-content').innerHTML =
                    `<div class="error">Error: ${error.message}</div>`;
            }
        }

        async function loadTable() {
            try {
                const response = await fetch('api/data');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                if (data.length === 0) {
                    document.getElementById('table-content').innerHTML = '<p>No data available</p>';
                    return;
                }
                const columns = Object.keys(data[0]);
                let html = '<table style="width:100%; border-collapse: collapse;">';
                html += '<thead><tr>' + columns.map(col =>
                    `<th style="border:1px solid #ddd; padding:8px; background:#f0f0f0;">${col}</th>`
                ).join('') + '</tr></thead><tbody>';
                data.slice(0, 50).forEach(row => {
                    html += '<tr>' + columns.map(col =>
                        `<td style="border:1px solid #ddd; padding:8px;">${row[col] ?? ''}</td>`
                    ).join('') + '</tr>';
                });
                html += '</tbody></table>';
                document.getElementById('table-content').innerHTML = html;
            } catch (error) {
                document.getElementById('table-content').innerHTML =
                    `<div class="error">Error: ${error.message}</div>`;
            }
        }

        loadMetadata();
        loadChart();
        loadTable();
    </script>
</body>
</html>
```

---

## Step 5: Test Locally Before Giving the Proxy URL

```bash
cd dashboard
python3 app.py &
sleep 2

# Test endpoints
curl -s http://localhost:8080/ | head -5
curl -s http://localhost:8080/api/metadata | jq .
curl -s http://localhost:8080/api/data | jq '.[0]'
```

## Step 6: Start Server & Provide URL

```bash
APP_UUID=$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)

cd dashboard
nohup python3 app.py > server.log 2>&1 &

echo "Dashboard running at:"
echo "https://workbench.verily.com/app/${APP_UUID}/proxy/8080/"
```

**Always provide the complete, working URL to the user — never placeholders.**

---

## Critical Server Configuration

### REQUIRED settings for Workbench dashboards:

```python
app.run(
    host='0.0.0.0',      # NOT localhost — proxy can't reach localhost
    port=8080,            # Match this to the port in your proxy URL
    debug=False,          # Security: don't use debug in shared environments
    threaded=True         # Allow concurrent users
)
```

---

## Troubleshooting

### No data showing

1. **Test API directly:** `curl http://localhost:8080/api/data | head -20`
2. **Check server logs:** `tail -f server.log`
3. **Check JS paths:** All `fetch()` must use relative paths (no leading `/`)

### Server won't start

```bash
lsof -i :8080
kill $(lsof -t -i :8080)
python3 app.py
```

### BigQuery errors (GCP)

```bash
# Check authentication
gcloud auth list

# Test BQ access
bq query --use_legacy_sql=false 'SELECT 1'

# Check project
gcloud config get-value project
```

If `to_dataframe()` fails with type errors, install `db-dtypes`:
`pip install --no-cache-dir db-dtypes`

### Aurora connection errors (AWS)

- `"PAM authentication failed"` -> not using IAM auth token as password
- `"pg_hba.conf rejects connection... no encryption"` -> missing `sslmode='require'`
- Consider using MCP tools (`mcp__wb__aurora_query`) instead of direct connections

### Changes not reflected after editing code

```bash
pkill -f "python3 app.py"
python3 app.py &
```

If changes still don't appear, hard-refresh the browser: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac).

### Server not accessible through proxy

Ensure Flask/FastAPI binds to `0.0.0.0`, not `localhost`:
```python
app.run(host='0.0.0.0', port=8080)
```

---

## Pre-Completion Checklist

Before declaring the dashboard complete, verify:

- [ ] **Relative paths** — All `fetch()` calls use `'api/...'` not `'/api/...'`
- [ ] **Host is 0.0.0.0** — Not `localhost` or `127.0.0.1`
- [ ] **threaded=True** — For concurrent users
- [ ] **debug=False** — For security
- [ ] **App UUID obtained** — Not using placeholder `[APP_UUID]`
- [ ] **Server running** — Process is active (`ps aux | grep python`)
- [ ] **Port correct** — URL uses same port as `app.run(port=...)`
- [ ] **CORS enabled** — `CORS(app)` added
- [ ] **Data cached** — Avoid repeated backend calls
- [ ] **Error handling** — API returns errors as JSON, not crashes
- [ ] **Tested locally** — `curl` tests pass before giving URL
- [ ] **Server logs checked** — API requests appear in logs

---

## Quick Reference

| Issue | Check | Fix |
|-------|-------|-----|
| 404 on API | JS path format | Remove leading `/` from `fetch()` |
| CORS error | CORS setup | Add `CORS(app)` |
| Blank page | Server running? | `ps aux \| grep python` |
| Works locally, fails via URL | Host binding | Change `localhost` to `0.0.0.0` |
| Gateway timeout | Server/UUID | Check server running + correct UUID |
| BQ data type error | Missing dep | `pip install db-dtypes` |
| BQ auth error | GCP credentials | `gcloud auth list` |
| Changes not showing | Cache/restart | Hard refresh + restart server |
| Address in use | Port conflict | `kill $(lsof -t -i :8080)` |
| Aurora: PAM auth failed | IAM auth | Use `wb resource credentials` + boto3 token |
| Aurora: no encryption | SSL missing | Add `sslmode='require'` |
