# ── Stage 1: build the React frontend ─────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /fe

# Install deps based on lockfile only
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build the SPA
COPY . ./
RUN npm run build


# ── Stage 2: runtime — serve the built SPA ────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install Flask to serve static files
RUN pip install --no-cache-dir flask flask-cors

# Copy built frontend from stage 1
COPY --from=frontend-build /fe/dist /app/dist
COPY --from=frontend-build /fe/public /app/public

# Copy server script
COPY server.py /app/server.py

EXPOSE 8080

# Container is long-running; restart:always in compose handles crashes
CMD ["python", "server.py"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/dashboard/health')" || exit 1
