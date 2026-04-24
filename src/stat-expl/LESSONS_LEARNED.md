# Lessons Learned: Workbench Custom App Deployment

Critical issues encountered and resolved during stat-expl deployment.

---

## 1. Workbench Reserves `/api/` Path
**Issue**: Using `/api/*` endpoints fails - Workbench reserves this path prefix.

**Solution**: Use `/dashboard/api/*` or another non-reserved prefix instead.

```python
# ❌ Wrong
@app.get("/api/health")

# ✅ Correct
@app.get("/dashboard/api/health")
```

---

## 2. Plotly.js: DON'T Use Browser Polyfills (They Break Builds)
**Issue**: Adding browser polyfills (buffer, stream-browserify, util) causes Vite builds to run out of memory, even with 4GB Node heap.

**ERROR**: `FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory`

**Solution**: Use `plotly.js-dist-min` WITHOUT polyfills. Modern browsers handle it fine.

```json
// package.json - CORRECT
"dependencies": {
  "plotly.js-dist-min": "^2.27.0",
  "react-plotly.js": "^2.6.0"
}

// ❌ DO NOT ADD: buffer, stream-browserify, util
```

```json
// package.json - build script needs memory limit
"scripts": {
  "build": "NODE_OPTIONS='--max-old-space-size=4096' vite build"
}
```

```typescript
// vite.config.ts - NO polyfill aliases needed
export default defineConfig({
  plugins: [react()],
  base: './',
  // ❌ DO NOT add resolve.alias or define for polyfills
})
```

**Why**: The polyfills themselves cause massive bundle bloat during Vite's build process, exhausting Node.js memory. Modern browsers support the APIs Plotly needs natively.

---

## 3. Assets Must Use Relative Paths
**Issue**: Workbench serves apps at `/app/<UUID>/proxy/8080/` - absolute paths break.

**Solution**: Configure Vite to emit relative paths:

```typescript
// vite.config.ts
export default defineConfig({
  base: './',  // Emit relative paths, not absolute
})
```

---

## 4. No Volume Mounts in docker-compose.yaml
**Issue**: Volume mounts in docker-compose.yaml break Workbench deployment.

**Solution**: Remove ALL volumes from docker-compose.yaml:

```yaml
# ❌ Wrong
services:
  app:
    volumes:
      - ./src:/app/src

# ✅ Correct - no volumes section at all
services:
  app:
    build:
      context: .
```

All files must be copied in Dockerfile, not mounted.

---

## 5. Multi-Stage Docker Build Pattern
**Issue**: Single-stage builds bloat production images with build tools.

**Solution**: Use multi-stage builds - Node.js for frontend, Python for runtime:

```dockerfile
# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime only
FROM python:3.11-slim AS runtime
WORKDIR /app
COPY backend/ /app/backend/
COPY --from=frontend-build /fe/dist /app/frontend/dist
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 6. StaticFiles Mount Order Matters
**Issue**: Mounting static files before API routes shadows API endpoints.

**Solution**: Register API routes FIRST, then mount StaticFiles LAST:

```python
# ✅ Correct order
@app.get("/dashboard/api/health")  # API routes first
def health():
    return {"status": "ok"}

# Static mount last
app.mount("/", StaticFiles(directory="dist", html=True), name="frontend")
```

---

## 7. Container Name Must Be "application-server"
**Issue**: Workbench looks for a specific container name.

**Solution**: Use exact name in docker-compose.yaml:

```yaml
services:
  app:
    container_name: "application-server"  # Must be this exact name
```

---

## 8. Git Submodules Break Workbench Cloning
**Issue**: Git submodule references without `.gitmodules` file cause deployment failures.

**Error**: `fatal: No url found for submodule path 'X' in .gitmodules`

**Solution**: Remove submodule references:
```bash
git rm --cached submodule-directory
echo "submodule-directory/" >> .gitignore
git commit -m "Remove broken submodule reference"
```

---

## 9. CLI Testing Requires Delete + Redeploy
**Issue**: `wb app stop` / `wb app start` restarts the existing container - doesn't rebuild from new code.

**Solution**: To test code changes via CLI, you MUST:
```bash
# ❌ Wrong - just restarts old container
wb app stop stat-expl
wb app start stat-expl

# ✅ Correct - rebuilds from latest code
wb app delete stat-expl
wb app create custom --name stat-expl \
  --repo-url https://github.com/org/repo.git \
  --branch your-branch \
  --folder-path src/stat-expl
```

**Why this matters**: Stop/start uses the cached Docker image. Only delete + create pulls fresh code and rebuilds the image.

**Best practice**: Use Workbench UI for testing during development - it's clearer that you're creating a fresh deployment.

---

## Debugging Strategy

For deployment failures:
1. Start with absolute minimum (health endpoint only)
2. Add complexity incrementally
3. Test each addition in deployment, not just locally
4. Compare with known working app (clinical-dashboard-from-myoung)

---

## Working Example Reference

**clinical-dashboard-from-myoung** structure:
```
src/clinical-dashboard/
├── .devcontainer.json
├── docker-compose.yaml
├── Dockerfile (multi-stage: Node → Python)
├── backend/
│   ├── pyproject.toml
│   └── app/
│       ├── __init__.py
│       └── main.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
```

Key patterns that work:
- FastAPI + StaticFiles with `html=True`
- Editable pip install: `pip install -e /app/backend`
- Frontend dist path: `Path(__file__).parent.parent.parent / "frontend" / "dist"`
- No HEALTHCHECK in Dockerfile (clinical-dashboard's is broken but works)
