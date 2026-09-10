FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/user-apps-artifacts/app-workbench-jupyter@sha256:8c529bc65213a832750b0bf8bf3cd6d07645eb9e5f0ea9e49b023d7608a34ed8 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh
