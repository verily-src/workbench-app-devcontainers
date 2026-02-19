# Creating Custom Workbench Apps

**Practical guide for creating simple, reliable Workbench apps.**

> **Official Reference:** https://github.com/verily-src/workbench-app-devcontainers
> 
> **Quick Start Script:** Use `./scripts/create-custom-app.sh` for auto-generated app structure!

---

## 🚀 Quick Start (Recommended)

The official repo has a script that generates a complete app structure:

```bash
# Clone the official repo
git clone https://github.com/verily-src/workbench-app-devcontainers.git
cd workbench-app-devcontainers

# Run the quick start script
./scripts/create-custom-app.sh my-app quay.io/jupyter/base-notebook 8888 jovyan /home/jovyan
```

This generates all required files in `src/my-app/` with correct structure.

**Arguments:**
- `app-name`: Name of your app
- `docker-image`: Base image (e.g., `python:3.11-slim`, `jupyter/base-notebook`)
- `port`: Port your app exposes (e.g., `8080`, `8888`)
- `username`: User inside container (default: `root`)
- `home-dir`: Home directory (default: `/root`)

---

## ⚠️ Critical Requirements

### 1. File Structure (MUST follow this exactly)

```
your-repo/
├── .devcontainer.json         ← MUST be at repo ROOT (not in a folder!)
├── docker-compose.yaml
├── Dockerfile
├── devcontainer-template.json
└── app/
    └── your_app.py
```

**⚠️ CRITICAL:** Workbench expects `.devcontainer.json` at the **repo ROOT**, NOT inside a `.devcontainer/` folder!

### 2. Container Requirements

Workbench custom apps need exactly **three things**:
1. Container named `application-server`
2. Connected to `app-network` (external Docker network)
3. HTTP server on a port

---

## The Working Pattern (Copy This)

### File 1: `.devcontainer.json`

**Location:** Repo ROOT (same level as docker-compose.yaml)

```json
{
  "name": "Your App Name",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/app",
  "remoteUser": "root"
}
```

**⚠️ CRITICAL settings:**
- `"dockerComposeFile": "docker-compose.yaml"` - Same directory (both at root)
- `"workspaceFolder": "/app"` - Should match WORKDIR in Dockerfile
- File MUST be named `.devcontainer.json` at repo root

### File 2: `docker-compose.yaml`

**Location:** Repository root

```yaml
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
```

**⚠️ CRITICAL settings:**
- `container_name: "application-server"` - Workbench looks for this exact name
- `networks: app-network` with `external: true` - Required for Workbench connectivity
- `volumes: - .:/app:cached` - Mounts code for live updates

### File 3: `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# CRITICAL: Must bind to 0.0.0.0 for Workbench proxy
CMD ["python", "app.py"]
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

## Common Mistakes Checklist

Before deploying, verify:

- [ ] `.devcontainer.json` is at repo ROOT (NOT in a folder!)
- [ ] `dockerComposeFile` is `"docker-compose.yaml"` (same directory)
- [ ] `container_name` is exactly `"application-server"`
- [ ] Network is `app-network` with `external: true`
- [ ] Flask/server binds to `0.0.0.0` (not `localhost`)
- [ ] Volume mount included for code updates

---

## ⚠️ Workbench App URLs (CRITICAL)

**When accessing your app, you MUST use this format:**

```
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
```

### Get App UUID:
```bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```

### ❌ WRONG Formats (Will fail)
```
https://abc123-def456.workbench-app.verily.com/  ← WRONG
http://localhost:8080/                            ← WRONG
```

---

## Flask App Example

```python
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
```

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| App fails to create / No container | `devcontainer.json` in wrong location | Move to repo ROOT as `.devcontainer.json` |
| App fails to create | `devcontainer.json` in `.devcontainer/` folder | Workbench needs it at ROOT, not in folder |
| "Bad Request" error | Wrong URL format | Use `workbench.verily.com/app/UUID/proxy/PORT/` |
| Server not accessible | Bound to `localhost` | Change to `host='0.0.0.0'` |
| Container restart loop | Process exits immediately | Ensure server runs continuously |

---

## Deployment

In Workbench UI, create custom app with:
- **Repository:** `https://github.com/YOUR-ORG/YOUR-REPO.git`
- **Branch:** `main`
- **Folder:** `.` (root) or `src/YOUR-APP-NAME` if in monorepo

---

## Local Testing

```bash
# Create required network
docker network create app-network

# Build and run
docker compose build
docker compose up

# Access at http://localhost:8080
```

---

## Reference Implementations

All examples: https://github.com/verily-src/workbench-app-devcontainers/tree/master/src

| App | Description | Port |
|-----|-------------|------|
| `playground/` | Simple multi-service example | 8080 |
| `vscode/` | VS Code Server | 8443 |
| `r-analysis/` | RStudio | 8787 |
| `workbench-jupyter/` | JupyterLab with tools | 8888 |

---

## When to Use Features

Sometimes you need the full-featured approach:

| Need | Solution |
|------|----------|
| Workbench CLI (`wb`) | Use `workbench-tools` feature |
| LLM/MCP integration | Use `wb-mcp-server` feature |
| Pre-authenticated gcloud | Use `workbench-tools` feature |

**If you need these, use the full `workbench-app-devcontainers` repo as your base.**
