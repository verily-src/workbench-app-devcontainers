#!/usr/bin/with-contenv bash
# shellcheck shell=bash
# Installs VS Code extensions once on first container boot.

[ -f /config/.extensions-installed ] && exit 0

HOME=/config s6-setuidgid abc /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /opt/geminicodeassist.vsix
HOME=/config s6-setuidgid abc /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /opt/claudecode.vsix

touch /config/.extensions-installed
