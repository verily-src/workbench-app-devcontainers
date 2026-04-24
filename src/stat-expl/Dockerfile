# Minimal test - just FastAPI server, no frontend build
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
 && rm -rf /var/lib/apt/lists/*

# Install FastAPI and uvicorn
RUN pip install --no-cache-dir fastapi uvicorn

# Copy server script
COPY server.py /app/server.py

# Create empty dist directory (so server doesn't crash)
RUN mkdir -p /app/dist

EXPOSE 8080

CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://127.0.0.1:8080/health || exit 1
