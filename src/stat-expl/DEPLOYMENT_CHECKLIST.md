# Deployment Checklist for stat-expl

## ✅ Required Files (All Present)

- [x] `.devcontainer.json` - Workbench container config
- [x] `docker-compose.yaml` - Container orchestration
- [x] `Dockerfile` - Multi-stage build (Node → Python)
- [x] `devcontainer-template.json` - App metadata
- [x] `server.py` - Flask server to serve React SPA
- [x] `.dockerignore` - Exclude unnecessary files from build
- [x] `package.json` - Node dependencies
- [x] `package-lock.json` - Locked dependencies
- [x] `vite.config.ts` - Vite config with base: '/dashboard/'
- [x] `tsconfig.json` - TypeScript config
- [x] `public/docs/schema.json` - 292KB dataset schema
- [x] `src/` - React app source code
- [x] `DEPLOYMENT.md` - Deployment instructions

## ✅ Configuration Verification

### .devcontainer.json
- [x] Located at folder root (src/stat-expl/)
- [x] `dockerComposeFile: "docker-compose.yaml"`
- [x] `service: "app"`
- [x] `workspaceFolder: "/app"`

### docker-compose.yaml
- [x] `container_name: "application-server"` (exact name required)
- [x] `networks: app-network` with `external: true`
- [x] `ports: "8080:8080"`
- [x] `restart: always`

### Dockerfile
- [x] Stage 1: Node 20 builds React with npm ci && npm run build
- [x] Stage 2: Python 3.11 runtime
- [x] Installs Flask and flask-cors
- [x] Copies dist/ and public/ from frontend-build stage
- [x] Copies server.py
- [x] Exposes port 8080
- [x] CMD runs server.py
- [x] Health check on /dashboard/health

### vite.config.ts
- [x] `base: '/dashboard/'` - Matches Flask routes
- [x] `allowedHosts` configured for Workbench proxy

### server.py
- [x] Flask routes start with `/dashboard/`
- [x] Health check at `/dashboard/health`
- [x] Schema served at `/dashboard/docs/schema.json`
- [x] SPA routes handled with client-side routing
- [x] `host='0.0.0.0'` (required for Workbench proxy)
- [x] `port=8080`

### .dockerignore
- [x] Excludes node_modules/
- [x] Excludes dist/ (will be built in container)
- [x] Excludes .git/
- [x] Excludes dev files

## ✅ Phase 1 Deliverables

- [x] Vite + React + TypeScript scaffold
- [x] CohortContext (filters, flags, variable tags)
- [x] schema.ts loader with utilities
- [x] Nav component
- [x] 5 placeholder pages + test page
- [x] Tailwind CSS configured
- [x] React Router configured

## 📋 Pre-Deployment Steps

1. **Push to GitHub:**
   ```bash
   cd /home/jupyter/temp-devcontainers
   git push origin stat-expl-v1
   ```

2. **Verify GitHub repo:**
   - Branch `stat-expl-v1` exists
   - Folder `src/stat-expl/` is present
   - All deployment files are committed

## 📋 Deployment Steps in Workbench UI

1. Navigate to Workbench workspace
2. Click **Apps** → **Create Custom App**
3. Fill in:
   - **Name**: `Dataset Statistical Explorer`
   - **Repository URL**: `https://github.com/verily-src/workbench-app-devcontainers.git` (or your fork)
   - **Branch**: `stat-expl-v1`
   - **Folder path**: `src/stat-expl`
   - **Machine type**: `n1-standard-2`
   - **Disk size**: 50 GB
4. Click **Create**
5. Wait 5-10 minutes for build

## 📋 Post-Deployment Verification

1. **Get App UUID:**
   ```bash
   wb app list --format=json | jq -r '.[] | select(.displayName == "Dataset Statistical Explorer") | .id'
   ```

2. **Access Health Check:**
   ```
   https://workbench.verily.com/app/<UUID>/proxy/8080/dashboard/health
   ```
   Should return: `{"status": "ok", "app": "stat-expl"}`

3. **Access Test Page:**
   ```
   https://workbench.verily.com/app/<UUID>/proxy/8080/dashboard/test
   ```
   Should show:
   - "Schema Loaded Successfully" section
   - 8 datasets, 25 tables, 651 columns
   - Context access test button

4. **Access Main App:**
   ```
   https://workbench.verily.com/app/<UUID>/proxy/8080/dashboard/
   ```
   Should redirect to Passport page

5. **Verify Navigation:**
   - All 5 pages accessible (Passport, Population, Variables, Quality, Hypotheses)
   - Nav bar shows correctly
   - No console errors

## 🔍 Troubleshooting

If health check fails:
- Check Workbench app logs: `wb app logs <app-name>`
- Verify container is running: `wb app describe <app-name>`

If white page appears:
- Open browser console (F12)
- Check for 404 errors on asset files
- Verify URL format is correct

If schema doesn't load:
- Check `/dashboard/docs/schema.json` endpoint directly
- Verify public/docs/schema.json exists in repo

## ✅ Ready to Deploy

All files are present and configured correctly. The app is ready to be deployed as a Workbench custom app.

**Next step:** Push to GitHub and create custom app in Workbench UI!
