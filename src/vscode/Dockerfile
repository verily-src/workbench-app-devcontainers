FROM lscr.io/linuxserver/code-server:4.100.3

# Download Gemini Code Assist VSIX at build time so no network is needed at runtime
RUN curl -L \
    "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/Google/vsextensions/geminicodeassist/latest/vspackage" \
    -o /opt/geminicodeassist.vsix

# Install the extension during container init, before code-server starts
COPY install-gemini.sh /etc/cont-init.d/99-install-gemini
RUN chmod +x /etc/cont-init.d/99-install-gemini

WORKDIR /config
