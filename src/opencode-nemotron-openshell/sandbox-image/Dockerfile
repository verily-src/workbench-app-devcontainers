# Workload image for OpenShell sandboxes running OpenCode. OpenShell replaces
# the image's entrypoint with its supervisor; opencode-sandbox.sh starts
# OpenCode with `openshell sandbox exec`.
FROM debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8

ARG OPENCODE_VERSION=1.18.22

# iproute2 is required by OpenShell for full network namespace isolation.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git iproute2 jq less \
        procps python3 python3-venv ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Same pinned OpenCode release as the app image. The policy names the real
# binary path, /opt/opencode/.opencode/bin/opencode.
RUN curl -fsSL https://opencode.ai/install -o /tmp/install-opencode.sh \
    && HOME=/opt/opencode bash /tmp/install-opencode.sh \
        --version "${OPENCODE_VERSION}" --no-modify-path \
    && rm /tmp/install-opencode.sh \
    && chmod -R a+rX /opt/opencode \
    && ln -s /opt/opencode/.opencode/bin/opencode /usr/local/bin/opencode \
    && HOME=/tmp opencode --version

COPY sandbox-image/sandbox-instructions.md /opt/opencode-sandbox/instructions.md

# /sandbox is the only writable directory besides /tmp, so it is also HOME:
# OpenCode keeps its sessions and logs under ~/.local/share/opencode.
RUN useradd --uid 1500 --home-dir /sandbox --create-home --shell /bin/bash sandbox \
    && install -d -o sandbox -g sandbox /sandbox/work

# Nothing in the sandbox may reach the internet, so turn off OpenCode features
# that would try: model catalog fetches, LSP and plugin downloads, updates and
# session sharing.
ENV HOME=/sandbox \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    OPENCODE_DISABLE_MODELS_FETCH=true \
    OPENCODE_DISABLE_LSP_DOWNLOAD=true \
    OPENCODE_DISABLE_DEFAULT_PLUGINS=true \
    OPENCODE_DISABLE_SHARE=true \
    OPENCODE_DISABLE_CLAUDE_CODE=true

USER sandbox
WORKDIR /sandbox/work
