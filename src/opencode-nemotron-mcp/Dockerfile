FROM lscr.io/linuxserver/code-server@sha256:7bd334657f13505abc1e20afeeee5670ad8f818e68853c810889184e597f3051

ARG OPENCODE_VERSION=1.18.22

RUN apt-get update \
    && apt-get install -y --no-install-recommends git jq openjdk-17-jre-headless \
        python3 python3-pip python3-venv ripgrep zstd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache \
    && chown -R abc:abc /config

RUN curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | tar --zstd -x -C /usr \
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

# Keep the picker available independently of the /workspace bind mount.
COPY configure-opencode.sh resolve-model.sh start-ollama.sh opencode-model.sh opencode-launch.sh models.json workbench-instructions.md /opt/opencode-workbench/
RUN chmod +x /opt/opencode-workbench/*.sh \
    && ln -s /opt/opencode-workbench/opencode-launch.sh /usr/local/bin/opencode \
    && ln -s /opt/opencode-workbench/opencode-model.sh /usr/local/bin/opencode-model

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
