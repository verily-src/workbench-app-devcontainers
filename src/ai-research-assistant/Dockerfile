FROM lscr.io/linuxserver/code-server@sha256:ec8f01d91c93a5d615224a306914c3ea9190c6237f876383591bca676a24fa67

# What this app adds to code-server itself. The local model (vLLM), the policy compiler, the
# sandbox commands and the OpenCode harness are devcontainer features (.devcontainer.json),
# installed into this image after it: features/src/vllm-model, ai-policy, agent-sandbox and
# opencode-harness.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git jq openjdk-17-jre-headless \
        python3 python3-pip python3-venv python3-yaml ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions /config/.cache \
    && chown -R abc:abc /config

# For the user's own code against the local model's API (the vllm-model feature), and a Python
# project tool.
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
