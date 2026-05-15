FROM lscr.io/linuxserver/code-server@sha256:7bd334657f13505abc1e20afeeee5670ad8f818e68853c810889184e597f3051

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache/huggingface \
    && chown -R abc:abc /config

RUN pip install --break-system-packages vllm openai --extra-index-url https://download.pytorch.org/whl/cu128

USER abc
ENV HOME=/config

RUN /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension ms-python.python

USER root
WORKDIR /config
