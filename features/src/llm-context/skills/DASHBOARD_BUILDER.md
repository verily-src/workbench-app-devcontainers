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
        return jsonify(get_bigquery_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

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

### Aurora connection errors (AWS)

- `"PAM authentication failed"` -> not using IAM auth token as password
- `"pg_hba.conf rejects connection... no encryption"` -> missing `sslmode='require'`
- Consider using MCP tools (`mcp__wb__aurora_query`) instead of direct connections

### Server not accessible through proxy

Ensure Flask/FastAPI binds to `0.0.0.0`, not `localhost`:
```python
app.run(host='0.0.0.0', port=8080)
```

---

## Quick Reference

| Issue | Check | Fix |
|-------|-------|-----|
| 404 on API | JS path format | Remove leading `/` from `fetch()` |
| CORS error | CORS setup | Add `CORS(app)` |
| Blank page | Server running? | `ps aux \| grep python` |
| Works locally, fails via URL | Host binding | Change `localhost` to `0.0.0.0` |
| Gateway timeout | Server/UUID | Check server running + correct UUID |
| Aurora: PAM auth failed | IAM auth | Use `wb resource credentials` + boto3 token |
| Aurora: no encryption | SSL missing | Add `sslmode='require'` |
