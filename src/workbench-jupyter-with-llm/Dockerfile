FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:7e7abd328398be0401d776daad043f7c54a14c42b4313e8a02ffddd4c494d382 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Pre-install web framework and data visualization libraries
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    flask flask-cors \
    plotly pandas boto3 psycopg2-binary
