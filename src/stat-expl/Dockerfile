# ── Stage 1: build the React frontend ─────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /fe

# Install deps based on lockfile only
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy only files needed for build
COPY vite.config.ts tsconfig.json tsconfig.node.json ./
COPY tailwind.config.js postcss.config.js ./
COPY index.html ./
COPY src/ ./src/
COPY public/ ./public/

# Build the SPA
RUN npm run build


# ── Stage 2: runtime — serve the built SPA ────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Minimal apt deps — build-essential for any Python dep that lacks a wheel
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Install FastAPI and uvicorn with standard extras
RUN pip install --no-cache-dir fastapi uvicorn[standard]

# Copy built frontend from stage 1
COPY --from=frontend-build /fe/dist /app/dist

# Copy public docs (schema.json) from frontend-build stage into dist
COPY --from=frontend-build /fe/public/docs /app/dist/docs

# Copy server script
COPY server.py /app/server.py

EXPOSE 8080

# Container is long-running; restart:always in compose handles crashes.
CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]

# HEALTHCHECK removed - clinical-dashboard's is broken but still works
