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

## ⚠️ Workbench App URLs (CRITICAL)

**When accessing your app or generating URLs for users, you MUST use this format:**

```
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
```

### Correct Examples
```
https://workbench.verily.com/app/abc123-def456/proxy/8080/
https://workbench.verily.com/app/abc123-def456/proxy/8501/dashboard
```

### ❌ WRONG Formats (Will fail with "Bad Request")
```
https://abc123-def456.workbench-app.verily.com/  ← WRONG
http://localhost:8080/                            ← WRONG
```

**Always use the proxy URL format. Never use localhost or custom domain patterns.**

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
