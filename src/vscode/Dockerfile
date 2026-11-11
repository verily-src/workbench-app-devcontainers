FROM lscr.io/linuxserver/code-server@sha256:a6d1aa1083f224d1ebb47bf9e2eb9a5624c5107447014912b768c27bb30293fc

# Gemini: https://open-vsx.org/extension/Google/geminicodeassist
# Claude: https://open-vsx.org/extension/Anthropic/claude-code
RUN apt-get update \
    && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /config/extensions \
    && chown abc:abc /config /config/extensions

USER abc
ENV HOME=/config

RUN curl -fsSL 'https://open-vsx.org/api/Google/geminicodeassist/2.79.0' \
        | jq -r '.files.download' \
        | xargs curl -fL --compressed -o /tmp/geminicodeassist.vsix \
    && curl -fsSL 'https://open-vsx.org/api/Anthropic/claude-code/linux-x64/2.1.128' \
        | jq -r '.files.download' \
        | xargs curl -fL --compressed -o /tmp/claudecode.vsix \
    && /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /tmp/geminicodeassist.vsix \
    && /app/code-server/bin/code-server --extensions-dir /config/extensions --install-extension /tmp/claudecode.vsix \
    && rm /tmp/geminicodeassist.vsix /tmp/claudecode.vsix \
    && mkdir -p /config/data/User \
    && echo '{"http.systemCertificatesNode":true}' > /config/data/User/settings.json

USER root

# Workbench embeds the app in a cross-origin iframe, where browsers refuse file
# pickers. Hide showDirectoryPicker so folder-sized and large-file downloads fall
# back to a direct download instead of failing silently. The script is served
# next to workbench.html and loaded with the page's script nonce. A content hash
# in the URL makes browsers fetch updates despite the year-long static cache.
ARG WORKBENCH_DIR=/app/code-server/lib/vscode/out/vs/code/browser/workbench
COPY static/disable-directory-picker.js ${WORKBENCH_DIR}/
RUN JS_HASH=$(md5sum ${WORKBENCH_DIR}/disable-directory-picker.js | cut -c1-12) \
    && sed -i "s|</head>|<script nonce=\"{{WORKBENCH_SCRIPT_NONCE}}\" src=\"{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/disable-directory-picker.js?v=${JS_HASH}\"></script></head>|" ${WORKBENCH_DIR}/workbench.html \
    && grep -q "disable-directory-picker.js?v=${JS_HASH}" ${WORKBENCH_DIR}/workbench.html

# Large downloads: stop VS Code reading the whole file before it starts the
# direct download. The build fails if the code it patches changes.
COPY static/patch-large-file-download.js /tmp/
RUN /app/code-server/lib/node /tmp/patch-large-file-download.js ${WORKBENCH_DIR}/workbench.js \
    && rm /tmp/patch-large-file-download.js \
    && WB_HASH=$(md5sum ${WORKBENCH_DIR}/workbench.js | cut -c1-12) \
    && sed -i "s|/out/vs/code/browser/workbench/workbench.js\"|/out/vs/code/browser/workbench/workbench.js?v=${WB_HASH}\"|" ${WORKBENCH_DIR}/workbench.html \
    && grep -q "workbench.js?v=${WB_HASH}" ${WORKBENCH_DIR}/workbench.html
# The patched bundle keeps its URL, which browsers cache for a year. The hash in
# the query string above makes them fetch the patched copy.

WORKDIR /config
