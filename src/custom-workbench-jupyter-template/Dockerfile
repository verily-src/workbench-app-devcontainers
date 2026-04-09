FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:c6e55356fa78187da382c76af331c6af1a0b48e82f5148872f5bdca55b00688b 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh
