FROM lscr.io/linuxserver/code-server@sha256:4524d0b00478e41264f42e0e660c1819e3b7d0c460f78ce73e44fa39b2b55134

ARG USER=abc
ARG HOME=/config
ARG WORKBENCH_DIR=/app/code-server/lib/vscode/out/vs/code/browser/workbench

# Show AoU policy reminders when files are uploaded or downloaded. The script is
# served next to workbench.html and loaded with the page's script nonce. Static
# files are cached for a year under a URL that only changes with the code-server
# version, so a content hash in the query string makes browsers fetch updates.
COPY static/aou-policy-interceptor.js static/aou-policy-styles.css ${WORKBENCH_DIR}/
RUN JS_HASH=$(md5sum ${WORKBENCH_DIR}/aou-policy-interceptor.js | cut -c1-12) \
    && CSS_HASH=$(md5sum ${WORKBENCH_DIR}/aou-policy-styles.css | cut -c1-12) \
    && sed -i "s|</head>|<link rel=\"stylesheet\" href=\"{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/aou-policy-styles.css?v=${CSS_HASH}\"><script nonce=\"{{WORKBENCH_SCRIPT_NONCE}}\" src=\"{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/aou-policy-interceptor.js?v=${JS_HASH}\"></script></head>|" ${WORKBENCH_DIR}/workbench.html \
    && grep -q "aou-policy-interceptor.js?v=${JS_HASH}" ${WORKBENCH_DIR}/workbench.html

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

# The user gets no sudo. linuxserver only enables it when SUDO_PASSWORD is set,
# which docker-compose.yaml leaves unset.
RUN rm -f /etc/sudoers.d/${USER}

# Remove the built-in GitHub Copilot extension and turn off VS Code's AI
# features (chat, inline suggestions) in the default user settings.
RUN rm -rf /app/code-server/lib/vscode/extensions/copilot

RUN mkdir -p /config/extensions /config/data/User \
    && echo '{"http.systemCertificatesNode":true,"chat.disableAIFeatures":true}' > /config/data/User/settings.json \
    && chown -R ${USER}:${USER} /config/extensions /config/data

# Spreadsheet-style editors: Edit csv for CSV files, Table Viewer for .xlsx files
# with formula evaluation. Neither declares untrusted-workspace support, so they
# only work once the user trusts the workspace or turns off workspace trust in
# VS Code settings.
# XDG_CONFIG_HOME points at a scratch dir because /config itself is root-owned.
RUN XDG_CONFIG_HOME=/tmp/xdg s6-setuidgid ${USER} /app/code-server/bin/code-server \
    --extensions-dir /config/extensions \
    --user-data-dir /config/data \
    --install-extension janisdd.vscode-edit-csv \
    --install-extension jbearak.table-viewer \
    && rm -rf /tmp/xdg

COPY --from=load-envs --chown=${USER} \
    /dist/load-env /dist/load-env.sh ${HOME}/

RUN echo "source ${HOME}/load-env.sh" >> ${HOME}/.bashrc \
    && chown ${USER}:${USER} ${HOME}/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227

WORKDIR /config
