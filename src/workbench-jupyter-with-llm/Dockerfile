FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:1dc9709007faf7b17810b01bd5c1dd439609e19e63a2fc34fb3afff9618d43bc 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Pre-install web framework and data visualization libraries
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    flask flask-cors \
    plotly pandas boto3 psycopg2-binary
