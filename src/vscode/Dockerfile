FROM lscr.io/linuxserver/code-server:4.100.3

# Gemini: https://open-vsx.org/extension/Google/geminicodeassist
# Claude: https://open-vsx.org/extension/Anthropic/claude-code
RUN apt-get update \
    && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://open-vsx.org/api/Google/geminicodeassist/latest" \
        | jq -r '.files.download' \
        | xargs curl -fL --compressed -o /opt/geminicodeassist.vsix

# Install extensions during container init, before code-server starts
COPY install-extensions.sh /etc/cont-init.d/99-install-extensions
RUN chmod +x /etc/cont-init.d/99-install-extensions

WORKDIR /config
