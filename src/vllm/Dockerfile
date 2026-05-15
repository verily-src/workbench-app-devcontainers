FROM lscr.io/linuxserver/code-server@sha256:7bd334657f13505abc1e20afeeee5670ad8f818e68853c810889184e597f3051

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq python3 python3-pip python3-venv \
    && curl -fsSL https://ollama.com/install.sh | sh \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache \
    && chown -R abc:abc /config

RUN pip install --break-system-packages openai

USER abc
ENV HOME=/config

RUN /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension ms-python.python

USER root
WORKDIR /config
