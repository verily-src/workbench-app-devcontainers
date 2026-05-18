FROM lscr.io/linuxserver/code-server@sha256:7bd334657f13505abc1e20afeeee5670ad8f818e68853c810889184e597f3051

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq python3 python3-pip python3-venv tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache \
    && chown -R abc:abc /config

RUN apt-get update && apt-get install -y --no-install-recommends zstd \
    && curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | tar --zstd -x -C /usr \
    && rm -rf /var/lib/apt/lists/* \
    && ollama --version

RUN pip install --break-system-packages openai

USER abc
ENV HOME=/config

RUN /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension ms-python.python \
    && mkdir -p /config/data/User \
    && echo '{"workbench.colorTheme":"Default Dark Modern"}' > /config/data/User/settings.json

USER root
WORKDIR /config
