FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install ONLY core dependencies (skip heavy ones like pandas, google-cloud-bigquery)
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    pydantic-settings==2.1.0

# Copy backend code
COPY backend/ /app/backend/

EXPOSE 8080

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://127.0.0.1:8080/api/health || exit 1
