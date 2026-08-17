FROM lscr.io/linuxserver/code-server@sha256:a6d1aa1083f224d1ebb47bf9e2eb9a5624c5107447014912b768c27bb30293fc

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
