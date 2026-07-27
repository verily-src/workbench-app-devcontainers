FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:8bf09394922d5f62ca97864f5ba3ad9c469a5d727235476a343a06f4d541ad49 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh
