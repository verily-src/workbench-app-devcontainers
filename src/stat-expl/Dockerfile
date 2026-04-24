# Step 3: Add Vite React build (no polyfills yet)
FROM node:20-alpine AS frontend-build

WORKDIR /fe

# Install deps
COPY package.json package-lock.json* ./
RUN npm install

# Build React app
COPY vite.config.ts index.html ./
COPY src/ ./src/
RUN npm run build

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn[standard]

COPY server.py /app/server.py
COPY --from=frontend-build /fe/dist /app/dist/

EXPOSE 8080

CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info"]
