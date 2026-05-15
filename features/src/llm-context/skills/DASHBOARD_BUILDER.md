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
```
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
```

### ⚠️ How to Get the App UUID (CRITICAL)

**You MUST automatically get the app UUID - NEVER ask the user for it.**

```bash
# Run this command and use the output:
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
https://workbench.verily.com/app/abc123-def456-789/proxy/8000/dashboard.html
```

### ❌ WRONG URL Formats (These WILL fail)
```
https://abc123-def456.workbench-app.verily.com/  ← WRONG: "Bad Request" error
https://workbench-app.verily.com/abc123-def456/  ← WRONG: Invalid domain
http://localhost:8080/                            ← WRONG: Not accessible externally
https://abc123-def456/workbench.verily.com/       ← WRONG: Reversed format
file:///home/jupyter/dashboard.html               ← WRONG: JavaScript blocked
```

### ⚠️ Common Issue: JavaScript API Calls Failing

**Problem:** JavaScript using absolute paths fails through Workbench proxy

**Symptoms:**
- Dashboard loads but shows no data
- Charts remain empty with "-" placeholders  
- Browser console shows 404 errors for API calls
- Flask/server logs show requests for `/` but NOT `/api/*` endpoints

### ✅ Solution: Use Relative Paths (TESTED & CONFIRMED)

**Always use relative paths (no leading `/`) for fetch/AJAX calls:**

```javascript
// ✅ CORRECT - relative paths work through proxy
fetch('api/metadata')
fetch('api/data?filter=value')

// ❌ WRONG - absolute paths fail
fetch('/api/metadata')  
fetch('/api/data?filter=value')
```

### Why Absolute Paths Fail

```
User visits: https://workbench.verily.com/app/UUID/proxy/8080/

Absolute path: fetch('/api/data')
  → Browser resolves to: https://workbench.verily.com/api/data ❌ (404!)

Relative path: fetch('api/data')  
  → Browser resolves to: https://workbench.verily.com/app/UUID/proxy/8080/api/data ✅
```

### Alternative: Embed Data in HTML (For Static Dashboards)

If you don't need dynamic filtering, embed data directly in the template:

**Python (Flask):**
```python
@app.route('/')
def index():
    data = get_data_from_bigquery()
    return render_template('dashboard.html', data_json=json.dumps(data))
```

**HTML Template:**
```html
<script>
const data = {{ data_json|safe }};
// Use data directly, no fetch calls needed
renderChart(data);
</script>
```

**When to use:** Static dashboards, large datasets that don't change, or when filters can be client-side only.

### Testing Checklist

Before deploying any web app:

- [ ] **Relative paths** - All `fetch()` calls use `'api/...'` not `'/api/...'`
- [ ] **Test locally** - `curl http://localhost:PORT/api/endpoint` returns data
- [ ] **Server logs** - Verify API requests arrive: `tail -f server.log`
- [ ] **Browser DevTools** - Network tab shows 200 status for API calls
- [ ] **App UUID obtained** - Not using placeholder `[APP_UUID]`

---

## Workflow

### Step 1: Understand Requirements

Ask the user:
1. **Data source?** BigQuery table, CSV in bucket, or local file?
2. **Visualizations?** Charts (bar, line, scatter), tables, filters?
3. **Interactivity?** Static display or dynamic filtering?

### Step 2: Auto-Detect Environment

**Always run these commands first:**

```bash
# Get app UUID (REQUIRED for final URL)
APP_UUID=$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)
echo "App UUID: $APP_UUID"

# Verify Python
python3 --version

# Check working directory
pwd
```

### Step 3: Install Dependencies

```bash
pip install flask flask-cors pandas plotly google-cloud-bigquery db-dtypes
```

> **Note:** `db-dtypes` is required for BigQuery to properly convert data types for pandas.

### Step 4: Create Dashboard Structure

```
dashboard/
├── app.py              # Flask server
├── templates/
│   └── index.html      # Dashboard HTML
└── static/
    └── style.css       # Optional styling
```

---

## Working Templates

### Template 1: Simple BigQuery Dashboard

**app.py:**
```python
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from google.cloud import bigquery
import os

app = Flask(__name__)
CORS(app)

# Cache for data
_data_cache = None

def get_bigquery_data():
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    
    client = bigquery.Client()
    query = """
    SELECT *
    FROM `YOUR_PROJECT.YOUR_DATASET.YOUR_TABLE`
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
        if data:
            return jsonify({
                "columns": list(data[0].keys()),
                "row_count": len(data)
            })
        return jsonify({"columns": [], "row_count": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # CRITICAL: host='0.0.0.0' required for Workbench proxy access
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

**templates/index.html:**
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
        <h1>📊 Data Dashboard</h1>
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
        // CRITICAL: Use relative paths (no leading slash!)
        const API_BASE = '';  // Empty string for relative paths
        
        async function loadMetadata() {
            try {
                const response = await fetch('api/metadata');  // Relative path!
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                document.getElementById('metadata-content').innerHTML = `
                    <p><strong>Columns:</strong> ${data.columns.join(', ')}</p>
                    <p><strong>Rows:</strong> ${data.row_count}</p>
                `;
            } catch (error) {
                document.getElementById('metadata-content').innerHTML = 
                    `<div class="error">Error loading metadata: ${error.message}</div>`;
                console.error('Metadata error:', error);
            }
        }

        async function loadChart() {
            try {
                const response = await fetch('api/data');  // Relative path!
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                
                if (data.length === 0) {
                    document.getElementById('chart-content').innerHTML = '<p>No data available</p>';
                    return;
                }

                // Create a simple bar chart with first numeric column
                const columns = Object.keys(data[0]);
                const numericCol = columns.find(col => typeof data[0][col] === 'number') || columns[1];
                const labelCol = columns[0];

                const chartData = [{
                    x: data.slice(0, 20).map(row => row[labelCol]),
                    y: data.slice(0, 20).map(row => row[numericCol]),
                    type: 'bar',
                    marker: { color: '#1976d2' }
                }];

                const layout = {
                    title: `${numericCol} by ${labelCol}`,
                    xaxis: { title: labelCol },
                    yaxis: { title: numericCol }
                };

                Plotly.newPlot('chart-content', chartData, layout);
            } catch (error) {
                document.getElementById('chart-content').innerHTML = 
                    `<div class="error">Error loading chart: ${error.message}</div>`;
                console.error('Chart error:', error);
            }
        }

        async function loadTable() {
            try {
                const response = await fetch('api/data');  // Relative path!
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                
                if (data.length === 0) {
                    document.getElementById('table-content').innerHTML = '<p>No data available</p>';
                    return;
                }

                const columns = Object.keys(data[0]);
                let html = '<table style="width:100%; border-collapse: collapse;">';
                html += '<thead><tr>' + columns.map(col => `<th style="border:1px solid #ddd; padding:8px; background:#f0f0f0;">${col}</th>`).join('') + '</tr></thead>';
                html += '<tbody>';
                data.slice(0, 50).forEach(row => {
                    html += '<tr>' + columns.map(col => `<td style="border:1px solid #ddd; padding:8px;">${row[col] ?? ''}</td>`).join('') + '</tr>';
                });
                html += '</tbody></table>';
                
                document.getElementById('table-content').innerHTML = html;
            } catch (error) {
                document.getElementById('table-content').innerHTML = 
                    `<div class="error">Error loading table: ${error.message}</div>`;
                console.error('Table error:', error);
            }
        }

        // Load all components
        loadMetadata();
        loadChart();
        loadTable();
    </script>
</body>
</html>
```

---

### Template 2: Multi-Chart Dashboard with Filters

**app.py additions:**
```python
@app.route('api/data')
def get_data():
    # Get filter parameters
    column = request.args.get('filter_column')
    value = request.args.get('filter_value')
    
    data = get_bigquery_data()
    
    if column and value:
        data = [row for row in data if str(row.get(column, '')) == value]
    
    return jsonify(data)

@app.route('api/filters')
def get_filters():
    data = get_bigquery_data()
    if not data:
        return jsonify({})
    
    # Get unique values for categorical columns
    filters = {}
    for col in data[0].keys():
        unique_values = list(set(str(row[col]) for row in data))
        if len(unique_values) < 50:  # Only include if reasonable number
            filters[col] = sorted(unique_values)
    
    return jsonify(filters)
```

**JavaScript filter implementation:**
```javascript
async function loadFilters() {
    const response = await fetch('api/filters');
    const filters = await response.json();
    
    const filterContainer = document.getElementById('filters');
    for (const [column, values] of Object.entries(filters)) {
        const select = document.createElement('select');
        select.id = `filter-${column}`;
        select.innerHTML = `<option value="">All ${column}</option>` +
            values.map(v => `<option value="${v}">${v}</option>`).join('');
        select.onchange = () => refreshData();
        
        filterContainer.appendChild(document.createTextNode(column + ': '));
        filterContainer.appendChild(select);
    }
}

async function refreshData() {
    const params = new URLSearchParams();
    document.querySelectorAll('select[id^="filter-"]').forEach(select => {
        if (select.value) {
            params.set('filter_column', select.id.replace('filter-', ''));
            params.set('filter_value', select.value);
        }
    });
    
    const response = await fetch(`api/data?${params}`);  // Still relative!
    const data = await response.json();
    updateCharts(data);
}
```

---

## Step 5: Test Locally

**Before starting the server, test your setup:**

```bash
# Start server in background
cd dashboard
python3 app.py &
sleep 2

# Test endpoints locally
echo "Testing root..."
curl -s http://localhost:8080/ | head -5

echo "Testing API..."
curl -s http://localhost:8080/api/metadata | jq .

echo "Testing data..."
curl -s http://localhost:8080/api/data | jq '.[0]'
```

---

## Step 6: Start Server & Provide URL

```bash
# Get the app UUID
APP_UUID=$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)

# Start server
cd dashboard
nohup python3 app.py > server.log 2>&1 &

echo "Dashboard running at:"
echo "https://workbench.verily.com/app/${APP_UUID}/proxy/8080/"
```

**Always provide the complete, working URL to the user - never placeholders!**

---

## ⚠️ Critical Flask Server Configuration

These settings are **REQUIRED** for Workbench dashboards to work:

### 1. Server MUST bind to 0.0.0.0 (NOT localhost)

```python
# ❌ WRONG - proxy cannot reach your app
app.run(host='localhost', port=8080)
app.run(host='127.0.0.1', port=8080)

# ✅ CORRECT - accessible through Workbench proxy
app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

**Why:** The Workbench proxy routes external requests to your app. If bound to localhost, the proxy cannot reach it.

### 2. Enable Threading for Concurrent Users

```python
app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

**Why:** Multiple users may access simultaneously. `threaded=True` allows concurrent request handling.

### 3. Disable Debug Mode

```python
# ❌ WRONG - security risk, auto-reload issues
app.run(debug=True)

# ✅ CORRECT
app.run(debug=False)
```

**Why:** Debug mode shouldn't be used in shared/production environments.

### 4. Restarting Server After Code Changes

Flask doesn't auto-reload when `debug=False`. After editing Python code:

```bash
# Find and kill existing server
pkill -f "python3 app.py"
# Or: kill $(lsof -t -i :8080)

# Restart
python3 app.py &
```

### 5. Browser Cache Issues

If changes don't appear after restarting server:
- **Hard refresh:** `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
- Flask caches templates - server restart clears this

---

## Troubleshooting

### Data doesn't load in browser

**1. Check paths in JavaScript:**
```javascript
// ❌ WRONG
fetch('/api/data')

// ✅ CORRECT
fetch('api/data')
```

**2. Check server logs:**
```bash
tail -f server.log
# Or if running in foreground, check terminal output
```

**3. Test API directly:**
```bash
curl http://localhost:8080/api/data | jq '.[0]'
```

**4. Check browser DevTools:**
- Open Network tab
- Look for failed requests (red)
- Check the URL being requested

### Server won't start

```bash
# Check if port is in use
lsof -i :8080

# Kill existing process
kill $(lsof -t -i :8080)

# Check Python errors
python3 app.py  # Run in foreground to see errors
```

### BigQuery errors

```bash
# Check authentication
gcloud auth list

# Test BQ access
bq query --use_legacy_sql=false 'SELECT 1'

# Check project
gcloud config get-value project
```

### Server not accessible through proxy (works locally, fails via URL)

**Symptom:** `curl http://localhost:8080/` works, but Workbench URL fails

**Cause:** Flask bound to `localhost` instead of `0.0.0.0`

**Fix:**
```python
# Change this:
app.run(host='localhost', port=8080)
# To this:
app.run(host='0.0.0.0', port=8080)
```

### Changes not reflected after editing code

**Cause 1:** Server not restarted
```bash
pkill -f "python3 app.py"
python3 app.py &
```

**Cause 2:** Browser cache
- Hard refresh: `Ctrl+Shift+R` or `Cmd+Shift+R`

### Gateway timeout

**Causes:**
1. Server not running: `ps aux | grep app.py`
2. Wrong UUID in URL: `wb app list --format=json`
3. Server bound to localhost (see above)

---

## Development Workflow (Recommended)

1. **Build and test locally first**
   ```bash
   curl http://localhost:8080/
   curl http://localhost:8080/api/metadata
   ```

2. **Check server logs for errors**
   ```bash
   tail -f server.log
   ```

3. **Only then test through Workbench proxy URL**

4. **Use browser DevTools (F12) → Network tab** to debug client-side issues

---

## Common Pitfalls Checklist

Before declaring the dashboard complete:

- [ ] **Relative paths** - All `fetch()` calls use `'api/...'` not `'/api/...'`
- [ ] **Host is 0.0.0.0** - Not `localhost` or `127.0.0.1`
- [ ] **threaded=True** - For concurrent users
- [ ] **debug=False** - For security
- [ ] **App UUID obtained** - Not using placeholder `[APP_UUID]`
- [ ] **Server running** - Process is active (`ps aux | grep python`)
- [ ] **Port correct** - URL uses same port as `app.run(port=...)`
- [ ] **CORS enabled** - `CORS(app)` added for cross-origin requests
- [ ] **Data cached** - Avoid repeated BigQuery calls
- [ ] **Error handling** - API returns errors as JSON, not crashes
- [ ] **Tested locally** - `curl` tests pass before giving URL
- [ ] **Server logs checked** - API requests appear in logs

---

## Quick Reference

| Issue | Check | Fix |
|-------|-------|-----|
| 404 on API | Path format | Remove leading `/` from fetch |
| CORS error | CORS setup | Add `CORS(app)` |
| Blank page | Server running? | `ps aux | grep python` |
| Data error | BigQuery auth | `gcloud auth list` |
| Wrong port | URL vs code | Match port in URL to `app.run()` |
| Works locally, fails via URL | Host binding | Change `localhost` to `0.0.0.0` |
| Gateway timeout | Server/UUID | Check server running + correct UUID |
| Address in use | Port conflict | `kill $(lsof -t -i :8080)` |
| Changes not showing | Cache/restart | Hard refresh + restart server |

---

## Example Prompts This Skill Handles

- "Create a dashboard showing data from my BigQuery table"
- "Build an interactive chart for analyzing patient demographics"
- "Visualize the CSV files in my bucket"
- "Make a web dashboard with filters for exploring data"
- "Display query results in a browser with charts"
