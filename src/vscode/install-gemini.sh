#!/usr/bin/with-contenv bash
# Installs Gemini Code Assist once on first container boot.
# Runs before code-server starts via s6-overlay cont-init.d.

[ -f /config/.gemini-installed ] && exit 0

s6-setuidgid abc code-server --install-extension /opt/geminicodeassist.vsix

touch /config/.gemini-installed
