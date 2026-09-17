FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/user-apps-artifacts/app-aou-jupyter@sha256:4283c7dd4d147f9847f01863b09be7e2ceb152c6d86f18264f3a97349b63f56f

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

COPY --from=aou-extension-builder --chown=$JUPYTER_USER \
    /dist/snippets $JUPYTER_USER_HOME_DIR/.local/share/jupyter/snippets

# Install aou extensions
RUN --mount=type=bind,from=aou-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

COPY --from=load-envs --chown=$JUPYTER_USER \
    /dist/load-env /dist/load-env.sh $JUPYTER_USER_HOME_DIR

RUN echo "source $JUPYTER_USER_HOME_DIR/load-env.sh" >> $JUPYTER_USER_HOME_DIR/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
