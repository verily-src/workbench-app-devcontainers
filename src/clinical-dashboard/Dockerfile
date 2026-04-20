# ── Stage 1: build the React frontend ─────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /fe

# Install deps based on lockfile only
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build the SPA
COPY frontend/ ./
RUN npm run build


# ── Stage 2: runtime — FastAPI serving /api + the built SPA ──────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc \
      curl \
 && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app/__init__.py /app/backend/app/__init__.py
RUN pip install --no-cache-dir -e /app/backend

# Copy backend code
COPY backend/ /app/backend/

# Copy built frontend from stage 1
COPY --from=frontend-build /fe/dist /app/frontend/dist

EXPOSE 8080

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1
