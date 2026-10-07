FROM node:22-alpine AS web-build
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm
# node in the runtime image so self_update.sh can rebuild the frontend
# in place — this is what makes restart-to-deploy possible.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
COPY --from=web-build /build/dist/ ./static/
# Bake the branch head at image build time; self_update.sh compares
# against it to no-op when there is nothing new. The ADD also busts the
# docker layer cache whenever the branch moves.
ADD https://api.github.com/repos/verily-src/workbench-app-devcontainers/commits/cohort-dashboard /tmp/build-commit.json
RUN python3 -c "import json; print(json.load(open('/tmp/build-commit.json'))['sha'])" > /app/APP_SHA \
    && rm /tmp/build-commit.json && chmod +x /app/self_update.sh
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
