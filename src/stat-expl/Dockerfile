# Absolute minimum - health endpoint only
FROM python:3.11-slim

WORKDIR /app

# Minimal system deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install FastAPI and uvicorn only
RUN pip install --no-cache-dir fastapi uvicorn[standard]

# Copy minimal server
COPY server.py /app/server.py

EXPOSE 8080

CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info"]
