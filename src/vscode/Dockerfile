FROM lscr.io/linuxserver/code-server:4.100.3

# Gemini: https://open-vsx.org/extension/Google/geminicodeassist
# Claude: https://open-vsx.org/extension/Anthropic/claude-code
RUN GEMINI_VERSION=$(curl -fsSL "https://open-vsx.org/api/Google/geminicodeassist/latest" | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4) && \
    curl -fL --compressed \
    "https://open-vsx.org/api/Google/geminicodeassist/${GEMINI_VERSION}/file/Google.geminicodeassist-${GEMINI_VERSION}.vsix" \
    -o /opt/geminicodeassist.vsix && \
    CLAUDE_VERSION=$(curl -fsSL "https://open-vsx.org/api/Anthropic/claude-code/latest" | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4) && \
    curl -fL --compressed \
    "https://open-vsx.org/api/Anthropic/claude-code/${CLAUDE_VERSION}/file/Anthropic.claude-code-${CLAUDE_VERSION}.vsix" \
    -o /opt/claudecode.vsix

# Install extensions during container init, before code-server starts
COPY install-extensions.sh /etc/cont-init.d/99-install-extensions
RUN chmod +x /etc/cont-init.d/99-install-extensions

WORKDIR /config
