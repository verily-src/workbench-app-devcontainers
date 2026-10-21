FROM lscr.io/linuxserver/code-server@sha256:7bd334657f13505abc1e20afeeee5670ad8f818e68853c810889184e597f3051

ARG OPENCODE_VERSION=1.18.22

RUN apt-get update \
    && apt-get install -y --no-install-recommends git jq openjdk-17-jre-headless \
        python3 python3-pip python3-venv ripgrep zstd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache \
    && chown -R abc:abc /config

COPY ollama-release.json /opt/opencode-workbench/ollama-release.json
RUN release_version="$(jq -r .version /opt/opencode-workbench/ollama-release.json)" \
    && release_sha256="$(jq -r .sha256 /opt/opencode-workbench/ollama-release.json)" \
    && curl --retry 3 -fsSL "https://github.com/ollama/ollama/releases/download/v${release_version}/ollama-linux-amd64.tar.zst" -o /tmp/ollama-runtime.tar.zst \
    && printf '%s  %s\n' "${release_sha256}" /tmp/ollama-runtime.tar.zst | sha256sum -c - \
    && tar --zstd -xf /tmp/ollama-runtime.tar.zst -C /usr \
    && rm /tmp/ollama-runtime.tar.zst \
    && ollama --version

# The installer hardcodes its target to ${HOME}/.opencode/bin. /config is a
# volume mount at run time, so install under /opt and link the binary instead.
# The base image sets HOME=/config for every user, including root. Override HOME
# so neither the installer nor the version check writes root-owned state into
# /config, which would stop the abc user from starting code-server.
RUN curl -fsSL https://opencode.ai/install -o /tmp/install-opencode.sh \
    && HOME=/opt/opencode bash /tmp/install-opencode.sh \
        --version "${OPENCODE_VERSION}" --no-modify-path \
    && rm /tmp/install-opencode.sh \
    && chmod -R a+rX /opt/opencode \
    && HOME=/opt/opencode /opt/opencode/.opencode/bin/opencode --version

# OpenShell CLI. Sandboxes run on the gateway container, not here; this
# container has no Docker socket.
ARG OPENSHELL_VERSION=0.1.4
ARG OPENSHELL_SHA256=2b65178e62e1ece1d90d482555e9f1f98ff0296e058409b33418104b6333df07
RUN curl --retry 3 -fsSL "https://github.com/NVIDIA/OpenShell/releases/download/v${OPENSHELL_VERSION}/openshell-x86_64-unknown-linux-musl.tar.gz" -o /tmp/openshell.tar.gz \
    && printf '%s  %s\n' "${OPENSHELL_SHA256}" /tmp/openshell.tar.gz | sha256sum -c - \
    && tar -xzf /tmp/openshell.tar.gz -C /usr/local/bin openshell \
    && rm /tmp/openshell.tar.gz \
    && OPENSHELL_TELEMETRY_ENABLED=false openshell --version

# Keep the picker available independently of the /workspace bind mount.
COPY available-models.sh configure-opencode.sh resolve-model.sh start-ollama.sh validate-model.sh gpu-check.py opencode-model.sh opencode-launch.sh opencode-sandbox.sh models.json workbench-instructions.md /opt/opencode-workbench/
COPY openshell/policy.yaml /opt/opencode-workbench/openshell/policy.yaml
RUN chmod +x /opt/opencode-workbench/*.sh \
    && ln -s /opt/opencode-workbench/opencode-launch.sh /usr/local/bin/opencode \
    && ln -s /opt/opencode-workbench/opencode-sandbox.sh /usr/local/bin/opencode-sandbox \
    && ln -s /opt/opencode-workbench/opencode-model.sh /usr/local/bin/opencode-model \
    && chmod +x /opt/opencode-workbench/gpu-check.py \
    && ln -s /opt/opencode-workbench/gpu-check.py /usr/local/bin/opencode-gpu-check

RUN pip install --break-system-packages openai uv

# Re-assert ownership after every root layer, in case one of them wrote to
# /config through the image-wide HOME=/config.
RUN chown -R abc:abc /config

USER abc
ENV HOME=/config

RUN /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension ms-python.python \
    && mkdir -p /config/data/User \
    && echo '{"workbench.colorTheme":"Default Dark Modern"}' > /config/data/User/settings.json

USER root
WORKDIR /config
