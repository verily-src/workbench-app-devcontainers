FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-aou-jupyter@sha256:d2ade6e50501a9094bd076df697b3dac16affc9346fc9ecc7c0b721d8bfbf34a

COPY --from=extension-builder --chown=$JUPYTER_USER \
    /dist/snippets $JUPYTER_USER_HOME_DIR/.local/share/jupyter/snippets

# Install all extensions we built
RUN --mount=type=bind,from=extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

COPY --from=load-envs --chown=$JUPYTER_USER \
    /dist/load-env /dist/load-env.sh $JUPYTER_USER_HOME_DIR

RUN echo "source $JUPYTER_USER_HOME_DIR/load-env.sh" >> $JUPYTER_USER_HOME_DIR/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
