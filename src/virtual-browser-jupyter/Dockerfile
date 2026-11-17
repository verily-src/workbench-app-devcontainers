FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:7ee11a17f62fb78444e53d7f844800aa1c63b734bd2a092c8eae3fb94d4d5e7c 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Remove sudo access
USER root
RUN rm -f /etc/sudoers.d/jupyter
USER jupyter
