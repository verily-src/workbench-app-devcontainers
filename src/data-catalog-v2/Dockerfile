# WB Data Catalog — multi-stage: Vite frontend + FastAPI backend
FROM node:20-bookworm-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install local packages first (they are dependencies for the backend)
COPY packages/verily-profiler /tmp/verily-profiler
RUN pip install --no-cache-dir /tmp/verily-profiler && rm -rf /tmp/verily-profiler

COPY packages/verily-chat /tmp/verily-chat
RUN pip install --no-cache-dir "/tmp/verily-chat[agent]" && rm -rf /tmp/verily-chat

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
COPY --from=frontend-build /build/dist /app/static
ENV FRONTEND_DIST=/app/static
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD curl -f http://localhost:8080/api/health || exit 1
CMD ["./start.sh"]
