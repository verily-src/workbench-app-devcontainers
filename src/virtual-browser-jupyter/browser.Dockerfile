FROM lscr.io/linuxserver/chromium@sha256:4c7b9086d2e5054b61c9e6b0f75efceece5befeff2bec3ff543d52e000cee21d

COPY initial_bookmarks.html /usr/share/chromium/initial_bookmarks.html

# Chromium reads every *.json under /etc/chromium/policies/managed/ at startup and applies it for
# the lifetime of the process. The policy is baked into the image on purpose: it must not be
# supplied through a compose bind mount, because the compose context is mounted as the user's
# workspace and anything under it is writable at runtime.
COPY policies/managed-policy.json /etc/chromium/policies/managed/workbench-rbi.json
