# Creating Custom Workbench Apps

> **Official Reference:** https://github.com/verily-src/workbench-app-devcontainers
> **Quick Start:** Use `./scripts/create-custom-app.sh` for auto-generated app structure

---

## ⚠️ Choose Your Pattern

| Pattern | Use When | Example |
|---------|----------|---------|
| **Minimal (Standalone)** | Simple apps, no cloud resources | `example` app in official repo |
| **Full-Featured (Monorepo)** | Need `wb` CLI, bucket mounting | Fork official repo |

---

## Pattern 1: Minimal Standalone App

Based on the `example` app in the [official repo](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/example).

### File Structure
```
your-repo/
├── .devcontainer.json         ← At repo ROOT
├── docker-compose.yaml
├── Dockerfile
├── devcontainer-template.json
└── app.py (or app/)
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

### File 2: `docker-compose.yaml`

**Minimal pattern:**
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
    networks:
      - app-network

networks:
  app-network:
    external: true
```

**Alternative: Use image directly (no Dockerfile):**
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

### File 3: `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
```

### File 4: `devcontainer-template.json`

```json
{
  "id": "my-app",
  "version": "1.0.0",
  "name": "My App",
  "description": "Description",
  "options": {},
  "platforms": ["Any"]
}
```

---

## Pattern 2: Multi-Container with Caddy Proxy

Useful when your app needs a reverse proxy. See the [r-analysis](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/r-analysis) app for an RStudio example with startup scripts.

```yaml
services:
  application-server:
    image: caddy:2.11-alpine
    container_name: application-server
    ports:
      - "8080:8080"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
    networks:
      - app-network
      - internal-network

  my-app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: my-app
    ports:
      - "3000:3000"
    networks:
      - internal-network

networks:
  app-network:
    external: true
  internal-network:
    driver: bridge
```

---

## Pattern 3: Full-Featured (Monorepo)

For apps needing `wb` CLI, bucket mounting, gcloud auth.

1. **Fork** https://github.com/verily-src/workbench-app-devcontainers
2. Run: `./scripts/create-custom-app.sh my-app python:3.11-slim 8080`
3. App created at `src/my-app/`
4. In Workbench, set **Folder** to `src/my-app`

---

## ⚠️ Critical Requirements

- [ ] `.devcontainer.json` at repo ROOT
- [ ] `container_name: "application-server"`
- [ ] `networks: app-network` with `external: true`
- [ ] Server binds to `0.0.0.0` (not `localhost`)

---

## ⚠️ Workbench App URLs

**Format:** `https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/`

```bash
# Get App UUID
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```

**❌ Wrong:** `https://abc123.workbench-app.verily.com/`

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
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
```

---

## Streamlit Example

```yaml
# docker-compose.yaml
services:
  app:
    container_name: "application-server"
    image: "python:3.11-slim"
    command: >
      bash -c "pip install streamlit &&
               streamlit run app.py --server.port=8501 --server.address=0.0.0.0"
    ports:
      - 8501:8501
    networks:
      - app-network

networks:
  app-network:
    external: true
```

---

## Deployment

In Workbench UI:
- **Repository:** `https://github.com/YOUR-ORG/YOUR-REPO.git`
- **Branch:** `main`
- **Folder:** `.` (standalone) or `src/my-app` (monorepo)

---

## Local Testing

```bash
docker network create app-network
docker compose up --build
# Access at http://localhost:PORT
```

---

## Reference Implementations

All examples are from the official repo: [verily-src/workbench-app-devcontainers](https://github.com/verily-src/workbench-app-devcontainers)

| App | Pattern | Description |
|-----|---------|-------------|
| [example](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/example) | Minimal | Reference implementation using ttyd terminal |
| [workbench-jupyter](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/workbench-jupyter) | Full-featured | JupyterLab with Workbench integration |
| [r-analysis](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/r-analysis) | Full-featured | RStudio with startup scripts |
| [workbench-vscode](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/workbench-vscode) | Full-featured | VS Code Server in browser |
| [playground](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/playground) | Minimal | Simple base environment |

---

## Common Errors

| Error | Possible Cause |
|-------|---------------|
| App fails to create | `.devcontainer.json` in wrong location |
| No container created | Check Workbench logs, GitHub access |
| Container restart loop | App crashes on startup (check `docker logs`) |
| "Bad Request" | Wrong URL format |
