FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:852517ee6ea1399c7c9ab1043827235564564056223ea412b82f6540de18cb8b 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Remove sudo access
USER root
RUN rm -f /etc/sudoers.d/jupyter
USER jupyter
