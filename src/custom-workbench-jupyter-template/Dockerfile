FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:0b38b47b7be3334d42103ee0176a6bcf90f2139517af117c0a18ce871c660d33 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh
