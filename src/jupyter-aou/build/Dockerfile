# Build the custom extension
FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:70ba6449275a581059f2f851f44bb8e4a1e5d42e73ec512af362e9de0618cf2f AS extension-builder

COPY extension /extension
# Original extension is https://github.com/QuantStack/jupyterlab-snippets;
# however, this does not support JupyterLab 4. There is an [open
# PR](https://github.com/QuantStack/jupyterlab-snippets/pull/43) to add
# JupyterLab 4 support, but it has not been merged and seems to be inactive, so
# we'll just build off of the PR branch for now.
ADD https://github.com/darpan097/jupyterlab-snippets.git#a27c8429d2cfaf7aa9e4cad31d3c641d554ac41a /extension/jupyterlab-snippets

RUN /build.sh /extension /dist

FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-aou-jupyter@sha256:6375f16454add4980acf83c75b70f6c7fce8668a674d2260a1ff0d20886ce60e

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

USER root
COPY remotefuse /opt/remotefuse
RUN chmod +x /opt/remotefuse/*
USER $JUPYTER_USER
