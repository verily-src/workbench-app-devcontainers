# Minimal + StaticFiles serving (no build step)
FROM python:3.11-slim

WORKDIR /app

# Minimal system deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install FastAPI and uvicorn only
RUN pip install --no-cache-dir fastapi uvicorn[standard]

# Copy server and static files
COPY server.py /app/server.py
COPY static/ /app/static/

EXPOSE 8080

CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info"]
