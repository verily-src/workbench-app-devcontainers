FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:5c4426ca8dcf08e6d3c19ed337884b2ad235aaafbe28962f7ef39f2a6d401095 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Pre-install web framework and data visualization libraries
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    flask flask-cors \
    plotly pandas boto3 psycopg2-binary
