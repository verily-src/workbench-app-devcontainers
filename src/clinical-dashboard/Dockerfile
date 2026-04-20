FROM python:3.11-slim

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

# Copy pre-built frontend (already committed to git, no Node.js build needed)
COPY frontend/dist/ /app/frontend/dist/

EXPOSE 8080

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://127.0.0.1:8080/api/health || exit 1
