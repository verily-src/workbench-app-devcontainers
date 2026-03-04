#!/usr/bin/with-contenv bash
# Installs VS Code extensions once on first container boot.
# Runs before code-server starts via s6-overlay cont-init.d.

[ -f /config/.extensions-installed ] && exit 0

s6-setuidgid abc code-server --install-extension /opt/geminicodeassist.vsix
s6-setuidgid abc code-server --install-extension /opt/claudecode.vsix

touch /config/.extensions-installed
