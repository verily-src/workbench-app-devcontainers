FROM lscr.io/linuxserver/code-server:4.100.3

# Download extension VSIXs at build time so no network is needed at runtime
RUN curl -L \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/Google/vsextensions/geminicodeassist/latest/vspackage" \
    -o /opt/geminicodeassist.vsix && \
    curl -L \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/anthropic/vsextensions/claude-code/latest/vspackage" \
    -o /opt/claudecode.vsix

# Install extensions during container init, before code-server starts
COPY install-extensions.sh /etc/cont-init.d/99-install-extensions
RUN chmod +x /etc/cont-init.d/99-install-extensions

WORKDIR /config
