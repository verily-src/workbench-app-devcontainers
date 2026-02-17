FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-aou-jupyter@sha256:f847557cb079c6404fb5f3f7702223e946d339e900744a065fb3d45de84e4337

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
