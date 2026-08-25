# Shared browser front end for exfil-compliant app templates: a server-side Chromium rendered by
# Selkies and streamed to the client as pixels, locked down by a managed enterprise policy.
#
# Consuming templates define their own `app` service pointing build.context at this directory
# (docker compose `include:` cannot override an imported service, so the service lives in the
# template, and the shared parts — policy, Selkies settings — live in this image). Templates set the
# APP_ORIGIN build arg (e.g. http://jupyterlab:8888); it is baked into the policy URLAllowlist so the
# browser can reach only that origin. With no APP_ORIGIN the allowlist is empty and, with
# URLBlocklist ["*"], the browser can reach nothing — it fails closed.
FROM lscr.io/linuxserver/chromium@sha256:4c7b9086d2e5054b61c9e6b0f75efceece5befeff2bec3ff543d52e000cee21d

# Selkies + hardening defaults; a template may override any of these in its compose environment.
ENV SELKIES_DESKTOP=false \
    NO_GAMEPAD=true \
    HARDEN_DESKTOP=true \
    HARDEN_KEYBINDS=true \
    DISABLE_CLOSE_BUTTON=true \
    RESTART_APP=true \
    SELKIES_FRAMERATE=20 \
    SELKIES_H264_CRF=28 \
    SELKIES_AUDIO_ENABLED=false \
    SELKIES_MICROPHONE_ENABLED=false \
    SELKIES_UI_SHOW_SIDEBAR="false|locked" \
    SELKIES_ENABLE_SHARING="false|locked" \
    SELKIES_ENABLE_COLLAB="false|locked" \
    SELKIES_ENABLE_SHARED="false|locked" \
    SELKIES_CLIPBOARD_OUT_ENABLED="false|locked" \
    SELKIES_COMMAND_ENABLED="false|locked" \
    SELKIES_FILE_TRANSFERS=upload

ARG APP_ORIGIN=""

# Chromium applies every *.json under /etc/chromium/policies/managed/ at startup. The policy is baked
# into the image, not bind-mounted: the app container's workspace mount is user-writable, so a mounted
# policy could be edited from inside the session.
COPY managed-policy.json.tmpl /tmp/managed-policy.json.tmpl
RUN mkdir -p /etc/chromium/policies/managed \
    && sed "s|__APP_ORIGIN__|${APP_ORIGIN}|g" /tmp/managed-policy.json.tmpl \
       > /etc/chromium/policies/managed/workbench-rbi.json \
    && rm /tmp/managed-policy.json.tmpl \
    && chmod 444 /etc/chromium/policies/managed/workbench-rbi.json
