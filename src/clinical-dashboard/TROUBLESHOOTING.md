# Troubleshooting - Fresh Branch Deployment

## ✅ Clean Branch Setup

This is a **fresh branch** (`cohort-multimodal-dashboard-v2`) created from `master` with no history from previous replacements.

### Branch Info
- **Branch**: `cohort-multimodal-dashboard-v2`
- **Base**: `master` (clean slate)
- **Repository**: `https://github.com/verily-src/workbench-app-devcontainers.git`
- **Folder**: `src/clinical-dashboard`

---

## 🚀 Deployment Steps

### 1. Create Workbench Custom App

```
Workbench UI → Apps → Create Custom App

Configuration:
├─ Repository: https://github.com/verily-src/workbench-app-devcontainers.git
├─ Branch: cohort-multimodal-dashboard-v2
├─ Folder path: src/clinical-dashboard
├─ Machine type: n1-highmem-2 (or n1-standard-4)
└─ Disk size: 50 GB
```

### 2. Monitor Build Progress

First build: ~5-10 minutes
```bash
wb app list
wb app logs <your-app-name> --follow
```

Expected build stages:
1. ✅ Cloning repository from GitHub
2. ✅ Building Docker image (multi-stage)
   - Stage 1: React frontend (npm install + build)
   - Stage 2: Python backend (pip install)
3. ✅ Starting container
4. ✅ Health check passes

### 3. Access Dashboard

Once status = `RUNNING`:
```bash
APP_UUID=$(wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1)
echo "https://workbench.verily.com/app/${APP_UUID}/proxy/8080/"
```

---

## 🔍 Verified Configuration

### Files Included
- ✅ `.devcontainer.json` - Workbench devcontainer config
- ✅ `docker-compose.yaml` - Container orchestration
- ✅ `Dockerfile` - Multi-stage build
- ✅ `backend/` - FastAPI application
- ✅ `frontend/` - React + TypeScript + Vite
- ✅ `README.md`, `DEPLOYMENT.md`, `FEATURES.md` - Documentation

### Workbench-Specific Settings

**docker-compose.yaml**:
```yaml
services:
  app:
    container_name: "application-server"  # Required exact name
    environment:
      APP_ENV: "prod"                     # Production mode
      USE_DEMO_TABLES: "true"
      BQ_PROJECT: "wb-spotless-eggplant-4340"
    networks:
      - app-network

networks:
  app-network:
    external: true                        # Workbench creates this
```

**.devcontainer.json**:
```json
{
  "service": "app",
  "shutdownAction": "none",               // Don't stop on disconnect
  "remoteUser": "root"                    // Run as root
}
```

---

## 🧪 Pre-Deployment Test (Optional)

Test locally before deploying to Workbench:

```bash
cd /home/jupyter/workbench-app-devcontainers/src/clinical-dashboard

# Create network
docker network create app-network 2>/dev/null || true

# Build
docker compose build

# Run
docker compose up

# Test in another terminal
curl http://localhost:8080/api/health
# Expected: {"status":"ok","env":"prod",...}

# Access dashboard: http://localhost:8080
```

---

## ❌ If Deployment Still Fails

### Step 1: Check Exact Error Message
```bash
wb app logs <your-app-name> --tail 200 > app_logs.txt
cat app_logs.txt
```

Look for:
- **Build errors**: npm/pip install failures
- **Runtime errors**: uvicorn startup issues
- **Health check failures**: /api/health not responding

### Step 2: Common Issues

#### Issue: "npm install" fails
**Solution**: Node version mismatch
```dockerfile
# Dockerfile uses: FROM node:20-alpine
# Ensure package.json is compatible with Node 20
```

#### Issue: "pip install" fails
**Solution**: Python dependencies missing
```bash
# Check backend/pyproject.toml
# Verify all packages are available on PyPI
```

#### Issue: Container starts but health check fails
**Debug**:
```bash
# SSH into app
wb app ssh <your-app-name>

# Check uvicorn process
ps aux | grep uvicorn

# Test health endpoint
curl http://127.0.0.1:8080/api/health

# Check Python errors
cat /app/backend/logs/*.log
```

#### Issue: Frontend blank page
**Check**:
- Browser console for 404 errors
- Network tab: verify `/api/health` returns 200
- Clear cache or use incognito mode

### Step 3: Verify BigQuery Access

The app needs read access to:
```
wb-spotless-eggplant-4340.analysis.DIAGNOSES
wb-spotless-eggplant-4340.crf.VS
wb-spotless-eggplant-4340.sensordata.*
```

Test from Workbench:
```bash
bq ls wb-spotless-eggplant-4340:analysis
bq ls wb-spotless-eggplant-4340:crf
bq ls wb-spotless-eggplant-4340:sensordata
```

If access denied, add resources to workspace:
```bash
wb resource add-ref bq-dataset \
  --name analysis \
  --project-id wb-spotless-eggplant-4340 \
  --dataset-id analysis
```

---

## 📊 Success Criteria

Dashboard is working if:

1. ✅ App status shows `RUNNING`
2. ✅ Health check passes: `curl .../proxy/8080/api/health` → 200 OK
3. ✅ Dashboard loads in browser
4. ✅ **Cohort Selector** page renders
5. ✅ Filter → Apply → Shows participant count
6. ✅ **Device Data** page shows Plotly charts
7. ✅ **Clinical Timeline** page shows BP/HR graphs

---

## 🆘 Still Having Issues?

### Collect Debug Info

```bash
# 1. App details
wb app describe <your-app-name> --format=json > app_details.json

# 2. Full logs
wb app logs <your-app-name> --tail 500 > full_logs.txt

# 3. Workspace info
wb workspace describe --format=json > workspace_info.json

# 4. Resource list
wb resource list --format=json > resources.json
```

### Contact Support

Email: support@workbench.verily.com

Include:
- App name
- Workspace ID
- Branch name: `cohort-multimodal-dashboard-v2`
- Error message
- Logs (attach full_logs.txt)
- What you've tried

---

## 📝 What's Different in This Branch?

vs. `clinical-dashboard-demo`:
- ✅ **Clean history** - No replacement artifacts
- ✅ **Fresh commit** - Single commit with all files
- ✅ **Verified config** - Docker-compose + devcontainer tested
- ✅ **Production settings** - APP_ENV=prod from start

If this branch works, we can delete `clinical-dashboard-demo` and use this one going forward.

---

**Last Updated**: 2026-04-19  
**Branch**: `cohort-multimodal-dashboard-v2` (fresh, clean)
