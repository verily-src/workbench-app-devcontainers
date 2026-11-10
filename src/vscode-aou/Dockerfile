FROM lscr.io/linuxserver/code-server@sha256:4524d0b00478e41264f42e0e660c1819e3b7d0c460f78ce73e44fa39b2b55134

ARG USER=abc
ARG HOME=/config
ARG WORKBENCH_DIR=/app/code-server/lib/vscode/out/vs/code/browser/workbench

# Show AoU policy reminders when files are uploaded or downloaded. The script is
# served next to workbench.html and loaded with the page's script nonce.
COPY static/aou-policy-interceptor.js static/aou-policy-styles.css ${WORKBENCH_DIR}/
RUN sed -i 's|</head>|<link rel="stylesheet" href="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/aou-policy-styles.css"><script nonce="{{WORKBENCH_SCRIPT_NONCE}}" src="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/aou-policy-interceptor.js"></script></head>|' ${WORKBENCH_DIR}/workbench.html \
    && grep -q aou-policy-interceptor.js ${WORKBENCH_DIR}/workbench.html

# The user gets no sudo. linuxserver only enables it when SUDO_PASSWORD is set,
# which docker-compose.yaml leaves unset.
RUN rm -f /etc/sudoers.d/${USER}

RUN mkdir -p /config/extensions /config/data/User \
    && echo '{"http.systemCertificatesNode":true}' > /config/data/User/settings.json \
    && chown -R ${USER}:${USER} /config/extensions /config/data

COPY --from=load-envs --chown=${USER} \
    /dist/load-env /dist/load-env.sh ${HOME}/

RUN echo "source ${HOME}/load-env.sh" >> ${HOME}/.bashrc \
    && chown ${USER}:${USER} ${HOME}/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227

WORKDIR /config
