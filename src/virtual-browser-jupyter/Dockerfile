FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:cc23dc0ddeec95bd1309275a68f3612a720e1d66dc03e5f0b1c2da93e185fe91 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Remove sudo access
USER root
RUN rm -f /etc/sudoers.d/jupyter
USER jupyter
