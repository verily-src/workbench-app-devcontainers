# Deployment Fixes for Workbench Custom App

## Issues Fixed

### 1. **Python Type Hints Compatibility** ✅
**Problem:** Code used Python 3.10+ union syntax (`str | None`) which caused import errors in Python 3.9.

**Fix:** Changed to `typing.Optional` for compatibility:
```python
# Before (Python 3.10+)
def filter_cohort(sex: str | None = None):

# After (Python 3.9+)
from typing import Optional
def filter_cohort(sex: Optional[str] = None):
```

**Files affected:**
- `backend/app/schemas/*.py`
- `backend/app/routers/cohorts.py`
- `backend/pyproject.toml` (lowered requirement to `>=3.9`)

---

### 2. **Multi-Stage Build Complexity** ✅
**Problem:** The original Dockerfile used a multi-stage build:
1. Node.js stage to build React frontend (`npm ci` + `npm run build`)
2. Python stage to run FastAPI backend

This likely **timed out** or **failed silently** during the Workbench VM build process.

**Evidence:**
- Original working Streamlit app: simple single-stage build ✅
- Failed React+FastAPI app: complex multi-stage build ❌

**Fix:** Simplified to single-stage build:
1. Pre-build the frontend locally: `npm run build`
2. Commit `frontend/dist/` to git (normally in `.gitignore`)
3. Dockerfile just copies pre-built files (no Node.js needed)

```dockerfile
# Before: Multi-stage build
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
...
COPY --from=frontend-build /fe/dist /app/frontend/dist

# After: Single-stage with pre-built frontend
FROM python:3.11-slim
WORKDIR /app
...
COPY frontend/dist/ /app/frontend/dist/
```

This matches the **working pattern** from the original Streamlit app.

---

### 3. **Removed Unnecessary Security Capabilities**
**Problem:** Added `cap_add`, `devices`, `security_opt` based on other examples (pgweb, test-app).

**Finding:** The **original working Streamlit app did NOT have these**. They're only needed for specific use cases (mounting workspace resources, Docker-in-Docker).

**Fix:** Removed from `docker-compose.yaml`:
```yaml
# Removed (not needed for this app):
cap_add:
  - SYS_ADMIN
devices:
  - /dev/fuse
security_opt:
  - apparmor:unconfined
```

---

## Root Cause Summary

The deployment failed because:
1. **Long build time:** Multi-stage builds with `npm ci` installing ~500 packages
2. **Silent failures:** Workbench only shows generic error, not build logs
3. **VM timeout:** Complex builds exceed Workbench's container launch timeout

## Solution

**Simplify the build** by pre-building frontend locally and committing artifacts. This reduces build time from ~60 seconds to ~10 seconds.

---

## How to Deploy

1. **Repository:** `https://github.com/verily-src/workbench-app-devcontainers.git`
2. **Branch:** `clinical-dashboard-simple`
3. **Folder:** `src/clinical-dashboard`
4. **Machine Type:** `n1-highmem-2`

The app should now deploy successfully with a fast, simple build.

---

## Lessons Learned

1. **Keep Workbench builds simple** - Complex multi-stage builds can timeout
2. **Pre-build assets locally** - Commit build artifacts for faster deployment
3. **Match working patterns** - If Streamlit worked, don't overcomplicate React
4. **Don't cargo-cult configs** - Not all examples need security capabilities
