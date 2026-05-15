# Web Apps & Dashboards Skill (AWS)

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

```bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```

**LLM INSTRUCTION:** When constructing dashboard/proxy URLs:
1. First run the command above to get the running app UUID
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
https://abc123-def456.workbench-app.verily.com/  <- WRONG
http://localhost:8080/                            <- WRONG: Not accessible externally
```

### Common Issue: JavaScript API Calls Failing

**Problem:** JavaScript using absolute paths fails through Workbench proxy

**Solution: Use Relative Paths (TESTED & CONFIRMED)**

```javascript
// CORRECT - relative paths work through proxy
fetch('api/metadata')
fetch('api/data?filter=value')

// WRONG - absolute paths fail
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

Aurora in Workbench uses **IAM database authentication** — you cannot connect with a static
password. The correct flow is:

1. Get temporary AWS credentials via `wb resource credentials`
2. Generate an IAM auth token via boto3 (token is valid for 15 minutes)
3. Connect with `sslmode='require'` — **SSL is mandatory; connections are rejected without it**

```python
import json, subprocess, boto3, psycopg2, pandas as pd, os

def get_aurora_connection(resource_id: str, username: str):
    """
    Returns an open psycopg2 connection to a Workbench-managed Aurora database.
    resource_id: the Workbench resource ID (e.g. 'test-db-1')
    username:    the IAM database user (check with your workspace admin)
    """
    # Step 1 — get temporary AWS credentials from Workbench
    result = subprocess.run(
        ['wb', 'resource', 'credentials',
         f'--id={resource_id}', '--scope=WRITE_READ', '--format=json'],
        capture_output=True, text=True, check=True
    )
    creds = json.loads(result.stdout)

    # Step 2 — parse connection details from WORKBENCH_* env var
    # Format: "host:port/dbname"  e.g. "abc.cluster.us-west-2.rds.amazonaws.com:5432/mydb"
    conn_str = os.environ.get(f'WORKBENCH_{resource_id.replace("-", "_")}', '')
    host_part, _, dbname = conn_str.partition('/')
    host, _, port = host_part.partition(':')
    port = int(port) if port else 5432

    # Step 3 — generate IAM auth token (valid 15 min)
    session = boto3.Session(
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken'],
        region_name='us-west-2'
    )
    auth_token = session.client('rds').generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=username, Region='us-west-2'
    )

    # Step 4 — connect with SSL (REQUIRED — Aurora rejects unencrypted connections)
    return psycopg2.connect(
        host=host, port=port, database=dbname,
        user=username, password=auth_token,
        sslmode='require'   # mandatory — omitting this causes "PAM authentication failed"
    )

def get_data_from_aurora():
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    conn = get_aurora_connection('test-db-1', 'your-iam-username')
    df = pd.read_sql('SELECT * FROM your_table LIMIT 1000', conn)
    conn.close()
    _data_cache = df.to_dict(orient='records')
    return _data_cache
```

> **Why IAM auth?** Workbench-managed Aurora databases are configured for IAM authentication only.
> Static passwords will fail with "PAM authentication failed" or "pg_hba.conf rejects connection".

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

Aurora requires IAM authentication + SSL. Plain password connections are rejected.

**Symptoms and causes:**
- `"PAM authentication failed"` -> not using IAM auth token as password
- `"pg_hba.conf rejects connection... no encryption"` -> missing `sslmode='require'`
- `"SSL connection is required"` -> same SSL issue

**Step-by-step fix:**

```bash
# 1. Get temporary credentials from Workbench (scoped to this resource)
wb resource credentials --id=<resource-id> --scope=WRITE_READ --format=json
# Returns: {"AccessKeyId":"...","SecretAccessKey":"...","SessionToken":"..."}
```

```python
import boto3, psycopg2, json, subprocess

# 2. Generate IAM auth token
result = subprocess.run(
    ['wb', 'resource', 'credentials', '--id=<resource-id>', '--scope=WRITE_READ', '--format=json'],
    capture_output=True, text=True, check=True
)
creds = json.loads(result.stdout)

session = boto3.Session(
    aws_access_key_id=creds['AccessKeyId'],
    aws_secret_access_key=creds['SecretAccessKey'],
    aws_session_token=creds['SessionToken'],
    region_name='us-west-2'
)
auth_token = session.client('rds').generate_db_auth_token(
    DBHostname='<aurora-endpoint>', Port=5432,
    DBUsername='<username>', Region='us-west-2'
)

# 3. Connect with SSL enabled (mandatory)
conn = psycopg2.connect(
    host='<aurora-endpoint>', port=5432, database='<dbname>',
    user='<username>', password=auth_token,
    sslmode='require'   # CRITICAL — without this, connection is rejected
)
```

**AWS CLI alternative (to verify the token works):**
```bash
# Export the credentials first
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."

# Generate auth token
TOKEN=$(aws rds generate-db-auth-token \
  --hostname <aurora-endpoint> --port 5432 \
  --region us-west-2 --username <username>)

# Connect (psql requires SSL flag)
PGSSLMODE=require psql "host=<aurora-endpoint> port=5432 dbname=<db> user=<username> password=$TOKEN"
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
- [ ] **Aurora: IAM auth** - Using `wb resource credentials` + boto3 token, not a static password
- [ ] **Aurora: SSL enabled** - `sslmode='require'` in psycopg2.connect()

---

## Quick Reference

| Issue | Check | Fix |
|-------|-------|-----|
| 404 on API | Path format | Remove leading `/` from fetch |
| CORS error | CORS setup | Add `CORS(app)` |
| Blank page | Server running? | `ps aux \| grep python` |
| S3 error | AWS credentials | `aws sts get-caller-identity` |
| Wrong port | URL vs code | Match port in URL to `app.run()` |
| Works locally, fails via URL | Host binding | Change `localhost` to `0.0.0.0` |
| Gateway timeout | Server/UUID | Check server running + correct UUID |
| Aurora: PAM auth failed | IAM auth | Use `wb resource credentials` + boto3 token |
| Aurora: no encryption | SSL missing | Add `sslmode='require'` to psycopg2.connect() |

---

## Example Prompts This Skill Handles

- "Create a dashboard showing data from my S3 bucket"
- "Build an interactive chart for analyzing patient demographics"
- "Visualize the CSV files in my bucket"
- "Make a web dashboard with filters for exploring data"
- "Display query results in a browser with charts"
