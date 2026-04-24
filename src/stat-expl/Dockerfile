# Minimal test - just FastAPI server, no frontend build
# Following clinical-dashboard-full-deps pattern with pyproject.toml
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (gcc for building Python packages)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gcc \
      curl \
 && rm -rf /var/lib/apt/lists/*

# Install backend dependencies via pyproject.toml
COPY pyproject.toml /app/pyproject.toml
COPY __init__.py /app/__init__.py
RUN pip install --no-cache-dir -e /app

# Copy server script
COPY server.py /app/server.py

# Create empty dist directory (so server doesn't crash)
RUN mkdir -p /app/dist

EXPOSE 8080

CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/dashboard/api/health || exit 1
