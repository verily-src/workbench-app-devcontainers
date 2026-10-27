FROM lscr.io/linuxserver/code-server@sha256:7bd334657f13505abc1e20afeeee5670ad8f818e68853c810889184e597f3051

# openjdk from apt rather than the devcontainers java feature: see the note in
# src/opencode-nemotron. post-startup.sh only needs /usr/bin/java for the wb CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git jq curl openjdk-17-jre-headless \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache \
    && chown -R abc:abc /config

# `aevom` helper: key management and stack status from the code-server terminal.
COPY aevom.sh /usr/local/bin/aevom
RUN chmod +x /usr/local/bin/aevom

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
