# Aevom API image for Workbench: upstream backend/Dockerfile, built from a
# pinned clone so that (a) the bionemo-agent-toolkit submodule is present and
# (b) workbench.patch can be applied to the frontend before it is bundled.
#
# The patch makes the React build proxy-friendly: Vite `base: "./"` plus a
# small shim that rewrites root-relative "/api/..." fetch/EventSource URLs,
# because the app is served under /proxy/8443/proxy/8000/ with the prefix
# stripped. Nothing else about Aevom is changed.
ARG AEVOM_COMMIT=2549b683e16cb4688ef7dc16851467f69e6c5e15

# Stage 0: pinned source checkout
FROM alpine/git:v2.54.0 AS src
ARG AEVOM_COMMIT
WORKDIR /src
RUN git clone https://github.com/NVIDIA-BioNeMo/agent-for-lifesciences.git . \
    && git checkout --detach "${AEVOM_COMMIT}" \
    && git submodule update --init --recursive --depth 1 \
    && git describe --tags --always > /src/.version
COPY workbench.patch /tmp/workbench.patch
RUN git apply --verbose /tmp/workbench.patch

# Stage 1: build the React frontend (as upstream)
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=src /src/frontend/package.json /src/frontend/package-lock.json* ./
RUN npm ci
COPY --from=src /src/frontend/ .
COPY --from=src /src/.version /tmp/version
RUN VERSION="$(cat /tmp/version)" npm run build

# Stage 2: FastAPI runtime (as upstream)
FROM python:3.11-slim
WORKDIR /app
COPY --from=src /src/.version /tmp/version
COPY --from=src /src/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=src /src/backend/api/ ./api/
COPY --from=src /src/deploy/openshell/pyexec-policy.yaml ./deploy/openshell/pyexec-policy.yaml
COPY --from=src /src/backend/skills/ ./skills/
COPY --from=src /src/backend/library-skills/ ./library-skills/
COPY --from=src /src/third_party/bionemo-agent-toolkit/nim-skills/ ./nim-skills/
COPY --from=src /src/NOTICE ./NOTICE
COPY --from=builder /app/dist ./static
COPY --from=src /src/prompts.md /prompts.md

# Keys arrive from the app container's ~/.aevom via the aevom-keys volume.
# Aevom reads fixed paths under /run/secrets, so link them to the volume.
RUN mkdir -p /run/secrets \
    && ln -s /run/aevom-keys/API_KEY_NV        /run/secrets/nvidia_api_key \
    && ln -s /run/aevom-keys/API_KEY_NVINF     /run/secrets/nvidia_api_key_nvinf \
    && ln -s /run/aevom-keys/API_KEY_ANTHROPIC /run/secrets/anthropic_api_key \
    && ln -s /run/aevom-keys/API_KEY_OPENAI    /run/secrets/openai_api_key
COPY aevom-api-entrypoint.sh /aevom-api-entrypoint.sh
RUN chmod 0755 /aevom-api-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/aevom-api-entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
