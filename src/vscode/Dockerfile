FROM lscr.io/linuxserver/code-server:4.100.3

# Download extension VSIXs at build time so no network is needed at runtime.
# To update: rebuild the image with --no-cache (latest version is pulled automatically).
# Gemini: https://marketplace.visualstudio.com/items?itemName=Google.geminicodeassist
# Claude: https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code
RUN curl -fL --compressed \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/Google/vsextensions/geminicodeassist/latest/vspackage" \
    -o /opt/geminicodeassist.vsix && \
    curl -fL --compressed \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/anthropic/vsextensions/claude-code/latest/vspackage" \
    -o /opt/claudecode.vsix

# Install extensions during container init, before code-server starts
COPY install-extensions.sh /etc/cont-init.d/99-install-extensions
RUN chmod +x /etc/cont-init.d/99-install-extensions

WORKDIR /config
