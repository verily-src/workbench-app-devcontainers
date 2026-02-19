# Creating Custom Workbench Apps

> **Official Reference:** https://github.com/verily-src/workbench-app-devcontainers

---

## ⚠️ Choose Your Pattern First

There are **TWO valid patterns** for Workbench custom apps:

| Pattern | Use When | Complexity |
|---------|----------|------------|
| **Simple (Standalone)** | Self-contained apps, no `wb` CLI needed | Minimal |
| **Full-Featured (Monorepo)** | Need `wb` CLI, bucket mounting, features | Requires monorepo structure |

**Most dashboards and simple apps should use Pattern 1.**

---

## Pattern 1: Simple Standalone App (Recommended for Dashboards)

Use this for Flask, Streamlit, or any self-contained app.

### Working Examples
- https://github.com/aculotti-verily/simple-dashboard-app
- https://github.com/aculotti-verily/r-shiny-demo-app

### File Structure
```
your-repo/
├── .devcontainer.json         ← At repo ROOT!
├── docker-compose.yaml
├── devcontainer-template.json
├── requirements.txt           ← (or package.json, etc.)
└── app.py                     ← Your application code
```

### File 1: `.devcontainer.json`

```json
{
  "name": "My App",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "remoteUser": "root"
}
```

**Key points:**
- NO `postCreateCommand` or `postStartCommand`
- NO `features` section
- File MUST be at repo ROOT (not in a folder)

### File 2: `docker-compose.yaml`

**Option A: Use image directly + install deps in command (simplest)**
```yaml
services:
  app:
    container_name: "application-server"
    image: "python:3.11-slim"
    restart: always
    working_dir: /workspace
    command: >
      bash -c "pip install -r requirements.txt &&
               python app.py"
    volumes:
      - .:/workspace:cached
    ports:
      - 8080:8080
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined

networks:
  app-network:
    external: true
```

**Option B: Build from Dockerfile (if you need custom setup)**
```yaml
services:
  app:
    container_name: "application-server"
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    volumes:
      - .:/workspace:cached
    ports:
      - 8080:8080
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined

networks:
  app-network:
    external: true
```

### File 3: `devcontainer-template.json`
```json
{
  "id": "my-app",
  "version": "1.0.0",
  "name": "My App",
  "description": "Description of my app",
  "options": {},
  "platforms": ["Any"]
}
```

### ⚠️ Critical Requirements

- [ ] `.devcontainer.json` at repo ROOT (not in `.devcontainer/` folder!)
- [ ] `container_name: "application-server"` (exact name)
- [ ] `networks: app-network` with `external: true`
- [ ] Server binds to `0.0.0.0` (not `localhost`)
- [ ] Include `cap_add`, `devices`, and `security_opt` sections

---

## Pattern 2: Full-Featured App (Monorepo)

Use this when you need:
- Workbench CLI (`wb`)
- Automatic bucket mounting
- Pre-authenticated `gcloud`/`aws`
- Devcontainer features

### How to Use
1. **Fork** https://github.com/verily-src/workbench-app-devcontainers
2. Run the quick start script:
   ```bash
   ./scripts/create-custom-app.sh my-app python:3.11-slim 8080 root /root
   ```
3. Customize the generated app in `src/my-app/`
4. Push to your fork
5. Create custom app in Workbench pointing to `src/my-app`

### Structure (in monorepo)
```
your-fork/
├── .devcontainer/
│   └── features/           ← Symlinks to features/src/
├── features/
│   └── src/
│       └── workbench-tools/
├── startupscript/
│   ├── post-startup.sh
│   └── remount-on-restart.sh
└── src/
    └── my-app/
        ├── .devcontainer.json
        ├── docker-compose.yaml
        └── devcontainer-template.json
```

### App's `.devcontainer.json` (Pattern 2)
```json
{
  "name": "my-app",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "postCreateCommand": [
    "./startupscript/post-startup.sh",
    "root",
    "/root",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "postStartCommand": [
    "./startupscript/remount-on-restart.sh",
    "root",
    "/root",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "features": {
    "./.devcontainer/features/workbench-tools": {
      "cloud": "${templateOption:cloud}",
      "username": "root",
      "userHomeDir": "/root"
    }
  },
  "remoteUser": "root"
}
```

**When using Pattern 2, the Folder field in Workbench UI should be `src/my-app`**

---

## ⚠️ Workbench App URLs (CRITICAL)

**When accessing your app, MUST use this format:**

```
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
```

### Get App UUID:
```bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```

### ❌ WRONG Formats
```
https://abc123-def456.workbench-app.verily.com/  ← WRONG
http://localhost:8080/                            ← WRONG
```

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| App fails to create / No container | `.devcontainer.json` in wrong location | Move to repo ROOT |
| App fails to create | Missing `startupscript/` in monorepo | Use Pattern 1, or fork official repo |
| Container restart loop | Process exits immediately | Ensure server runs continuously |
| Server not accessible | Bound to `localhost` | Change to `host='0.0.0.0'` |
| "Bad Request" error | Wrong URL format | Use proxy URL format |
| Features not found | Using Pattern 2 without monorepo structure | Use Pattern 1 for standalone apps |

---

## Flask App Example (Pattern 1)

**app.py:**
```python
from flask import Flask
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return '<h1>Hello Workbench!</h1>'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

**requirements.txt:**
```
flask>=3.0.0
flask-cors>=4.0.0
```

---

## Streamlit Example (Pattern 1)

**docker-compose.yaml:**
```yaml
services:
  app:
    container_name: "application-server"
    image: "python:3.11-slim"
    restart: always
    working_dir: /workspace
    command: >
      bash -c "pip install -r requirements.txt &&
               streamlit run app.py --server.port=8501 --server.address=0.0.0.0"
    volumes:
      - .:/workspace:cached
    ports:
      - 8501:8501
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined

networks:
  app-network:
    external: true
```

---

## Deployment

In Workbench UI:
- **Repository:** `https://github.com/YOUR-ORG/YOUR-REPO.git`
- **Branch:** `main`
- **Folder:** `.` (Pattern 1) or `src/my-app` (Pattern 2)

---

## Local Testing

```bash
# Create required network
docker network create app-network

# Build and run
docker compose up --build

# Access at http://localhost:PORT
```

---

## Reference Implementations

| App | Pattern | Port | Description |
|-----|---------|------|-------------|
| [simple-dashboard-app](https://github.com/aculotti-verily/simple-dashboard-app) | 1 | 8501 | Streamlit dashboard |
| [r-shiny-demo-app](https://github.com/aculotti-verily/r-shiny-demo-app) | 1 | 8080 | RShiny with Caddy |
| [playground](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/playground) | 1 | 8080 | Multi-service example |
| [workbench-jupyter](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/workbench-jupyter-docker) | 2 | 8888 | Full JupyterLab |
| [r-analysis](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/r-analysis) | 2 | 8787 | RStudio with features |

---

## Decision Flowchart

```
Do you need wb CLI, bucket mounting, or gcloud auth?
  │
  ├── NO → Use Pattern 1 (Simple Standalone)
  │         - Create single repo
  │         - .devcontainer.json at ROOT
  │         - No features, no startup scripts
  │
  └── YES → Use Pattern 2 (Full-Featured Monorepo)
            - Fork verily-src/workbench-app-devcontainers
            - Run ./scripts/create-custom-app.sh
            - App goes in src/my-app/
            - Folder field = "src/my-app"
```
