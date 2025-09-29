FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-aou-jupyter@sha256:e6dbe09147d2f2431131ad922692349be35364c530013a0ce31f0db71efafde9

COPY --from=extension-builder --chown=$JUPYTER_USER \
    /dist/snippets $JUPYTER_USER_HOME_DIR/.local/share/jupyter/snippets

# Install all extensions we built
RUN --mount=type=bind,from=extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
