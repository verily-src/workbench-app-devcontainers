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
#
# Display stays on the default Wayland stack (auto-fits each client's window). The click-offset it
# would otherwise cause is fixed by --disable-features=WaylandFractionalScaleV1 in the template's
# CHROME_CLI — a known upstream Chromium/Wayland fractional-scaling bug.
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
    && rm /tmp/managed-policy.json.tmpl

# The Selkies client negotiates the click-coordinate mapping at initial load, before the streamed
# iframe has settled to its final size, so clicks land offset until the resolution is re-negotiated
# (which is why opening devtools or resizing the window "fixes" it). A synthetic resize event is a
# no-op when dimensions haven't actually changed; instead post the client's own
# "resetResolutionToWindow" message, which recomputes resolution from the container's current size.
# Staggered timers catch the post-connect settle. This inline script runs before the deferred client
# module, so the listener is attached by the time the timers fire.
RUN sed -i 's|</head>|<script>[800,2000,4000].forEach(function(t){setTimeout(function(){window.postMessage({type:"resetResolutionToWindow"},window.location.origin)},t)})</script></head>|' \
    /usr/share/selkies/selkies-dashboard/index.html
