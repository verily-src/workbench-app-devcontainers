FROM lscr.io/linuxserver/code-server@sha256:99988f89acaa4243bc2b2cfa08ae1465c9d24404c59f3a457ad36ea57febb151

# Gemini: https://open-vsx.org/extension/Google/geminicodeassist
# Claude: https://open-vsx.org/extension/Anthropic/claude-code
RUN apt-get update \
    && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions \
    && chown abc:abc /config /config/extensions

USER abc
ENV HOME=/config

RUN curl -fsSL 'https://open-vsx.org/api/Google/geminicodeassist/2.79.0' \
        | jq -r '.files.download' \
        | xargs curl -fL --compressed -o /tmp/geminicodeassist.vsix \
    && curl -fsSL 'https://open-vsx.org/api/Anthropic/claude-code/linux-x64/2.1.128' \
        | jq -r '.files.download' \
        | xargs curl -fL --compressed -o /tmp/claudecode.vsix \
    && /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /tmp/geminicodeassist.vsix \
    && /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /tmp/claudecode.vsix \
    && rm /tmp/geminicodeassist.vsix /tmp/claudecode.vsix \
    && mkdir -p /config/data/User \
    && echo '{"http.systemCertificatesNode":true}' > /config/data/User/settings.json

USER root

WORKDIR /config
