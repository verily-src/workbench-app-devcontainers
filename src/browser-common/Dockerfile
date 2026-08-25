# Shared browser front end: a server-side Chromium rendered by Selkies and streamed to the client as
# pixels, locked down by a managed policy. Consuming templates build their own `app` service from this
# context and set APP_ORIGIN, baked into the policy URLAllowlist (with none, URLBlocklist ["*"] makes
# it fail closed).
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

# Chromium applies every *.json under /etc/chromium/policies/managed/ at startup. Baked into the image
# (not bind-mounted) and chmod 444, so it can't be modified from the user-writable session.
COPY managed-policy.json.tmpl /tmp/managed-policy.json.tmpl
RUN mkdir -p /etc/chromium/policies/managed \
    && sed "s|__APP_ORIGIN__|${APP_ORIGIN}|g" /tmp/managed-policy.json.tmpl \
       > /etc/chromium/policies/managed/workbench-rbi.json \
    && rm /tmp/managed-policy.json.tmpl \
    && chmod 444 /etc/chromium/policies/managed/workbench-rbi.json
