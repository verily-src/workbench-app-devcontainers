# Build the custom extension
FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:10896c245e1329f6fcbc37c7253d654d3b7dd65cf4c50975b27fe55e40dcc69f AS extension-builder

COPY extension /extension
# Original extension is https://github.com/QuantStack/jupyterlab-snippets;
# however, this does not support JupyterLab 4. There is an [open
# PR](https://github.com/QuantStack/jupyterlab-snippets/pull/43) to add
# JupyterLab 4 support, but it has not been merged and seems to be inactive, so
# we'll just build off of the PR branch for now.
ADD https://github.com/darpan097/jupyterlab-snippets.git#a27c8429d2cfaf7aa9e4cad31d3c641d554ac41a /extension/jupyterlab-snippets

RUN /build.sh /extension /dist

FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-aou-jupyter@sha256:c18c4f2069f123d2436f28e2e51363a69b109ae4151c6d53d0a7348b5e437263

COPY snippets $JUPYTER_USER_HOME_DIR/.local/share/jupyter/snippets

# Disable some of the default jupyterlab extensions. We will override these with
# the aou-jupyterlab extension
RUN jupyter labextension disable @jupyterlab/filebrowser-extension:download && \
    jupyter labextension disable @jupyterlab/filebrowser-extension:open-browser-tab && \
    jupyter labextension disable @jupyterlab/docmanager-extension:download && \
    jupyter labextension disable @jupyterlab/docmanager-extension:open-browser-tab && \
    jupyter labextension disable @jupyterlab/notebook-extension:export

# Install all extensions we built
RUN --mount=type=bind,from=extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/install.sh

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
USER $JUPYTER_USER
