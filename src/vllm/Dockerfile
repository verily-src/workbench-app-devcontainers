FROM vllm/vllm-openai:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq sudo curl \
    && curl -fsSL https://code-server.dev/install.sh | sh \
    && pip install openai \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /config/extensions /workspace \
    && useradd -u 1000 -s /bin/bash -d /config abc || true \
    && chown -R abc:abc /config /workspace /tmp

RUN echo "abc ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/abc \
    && chmod 0440 /etc/sudoers.d/abc

USER abc
ENV HOME=/config

RUN code-server --install-extension ms-python.python

USER root
WORKDIR /config
