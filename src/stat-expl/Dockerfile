# Step 5: Match clinical-dashboard folder structure
FROM node:20-alpine AS frontend-build

WORKDIR /fe

# Install deps
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build React app
COPY frontend/ ./
RUN npm run build

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install backend Python deps (editable install via pyproject.toml)
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app/__init__.py /app/backend/app/__init__.py
RUN pip install --no-cache-dir -e /app/backend

# Full backend source
COPY backend/ /app/backend/

# Drop built frontend where main.py expects it
COPY --from=frontend-build /fe/dist /app/frontend/dist

EXPOSE 8080

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info", \
     "--access-log"]
