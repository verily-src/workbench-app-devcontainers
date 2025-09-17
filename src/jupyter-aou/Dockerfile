FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-aou-jupyter@sha256:c18c4f2069f123d2436f28e2e51363a69b109ae4151c6d53d0a7348b5e437263

COPY --from=extension-builder /dist/snippets $JUPYTER_USER_HOME_DIR/.local/share/jupyter/snippets

# Install all extensions we built
RUN --mount=type=bind,from=extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
