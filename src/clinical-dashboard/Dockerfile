# ── Stage 1: build the React frontend ─────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /fe

# Install deps based on lockfile only — maximal layer cache.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build the SPA. `base: './'` in vite.config.ts emits relative asset paths so
# the bundle works behind Workbench's /app/<UUID>/proxy/8080/ prefix.
COPY frontend/ ./
RUN npm run build


# ── Stage 2: runtime — FastAPI serving /api + the built SPA ──────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Minimal apt deps — pyarrow wheels need libgomp; build-essential only needed
# if any Python dep lacks a wheel (keep for safety, small image cost).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Install backend Python deps (editable install via pyproject.toml).
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app/__init__.py /app/backend/app/__init__.py
RUN pip install --no-cache-dir -e /app/backend

# Full backend source (overwrites the stub __init__.py above).
COPY backend/ /app/backend/

# Drop the built frontend where main.py expects it: _FRONTEND_DIST is
# <file>.parent.parent.parent / "frontend" / "dist" → /app/frontend/dist
COPY --from=frontend-build /fe/dist /app/frontend/dist

EXPOSE 8080

# Container is long-running; restart:always in compose handles crashes.
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1
