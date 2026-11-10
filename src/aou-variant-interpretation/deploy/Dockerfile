# Build context is the repository root (see docker-compose.yaml), so paths
# below are relative to the top of the repo, not this folder.

FROM node:22-alpine AS ui-build
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ .
RUN npm run build

FROM gradle:8.14.1-jdk21-noble AS api-build
WORKDIR /api
COPY api/settings.gradle api/build.gradle api/gradlew ./
COPY api/gradle ./gradle
RUN ./gradlew --no-daemon dependencies
COPY api/src ./src
COPY --from=ui-build /ui/dist ./src/main/resources/static
RUN ./gradlew --no-daemon bootJar -x test

FROM eclipse-temurin:21-jre-noble
WORKDIR /app
# post-startup.sh (run as root via postCreateCommand, see .devcontainer.json) requires
# these -- sudo in particular, since it runs every step as the app user via
# `sudo -u via bash -l -c ...`, and fails immediately without it. The rest are
# what its package check looks for; baking them in makes that step a no-op
# instead of an apt-get update on every boot.
RUN apt-get update && \
    apt-get install -y --no-install-recommends sudo jq git lsb-release curl tar wget && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# AoU Researcher Workbench exfiltration controls (see deploy/README.md): the app runs as
# an unprivileged user with no way back to root. The user is deliberately not in sudoers
# (sudo stays installed only so root's post-startup.sh can drop *down* to this user), and
# the sudoers.d entry is removed defensively in case a base image ever ships one, as the
# upstream r-analysis-aou template does for its rstudio user.
ARG USER=via
ARG HOME=/home/${USER}
RUN useradd --create-home --home-dir "${HOME}" --shell /bin/bash "${USER}" && \
    rm -f "/etc/sudoers.d/${USER}"

COPY --from=api-build /api/build/libs/*.jar app.jar
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
EXPOSE 8080
USER ${USER}
ENV HOME=${HOME}
ENTRYPOINT ["/app/entrypoint.sh"]
