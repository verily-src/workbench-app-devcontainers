FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:5c4426ca8dcf08e6d3c19ed337884b2ad235aaafbe28962f7ef39f2a6d401095 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Remove sudo access
USER root
RUN rm -f /etc/sudoers.d/jupyter
USER jupyter
