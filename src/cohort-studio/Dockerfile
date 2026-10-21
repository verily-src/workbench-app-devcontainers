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
    && apt-get install -y --no-install-recommends nodejs util-linux \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
COPY --from=web-build /build/dist/ ./static/
# A caller may supply the exact source commit. Do not query the branch head
# here: it can move independently of the checked-out build context.
ARG APP_SHA=unknown
RUN printf '%s\n' "$APP_SHA" > /app/APP_SHA \
    && chmod +x /app/self_update.sh
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
