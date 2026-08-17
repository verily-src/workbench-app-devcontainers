FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-workbench-jupyter@sha256:7e32fa4c82d9ec5381b81e2673ff9e15f8eed0b767e3a83bb4a2d84714dbe4eb 

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# Pre-install web framework and data visualization libraries
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    flask flask-cors \
    plotly pandas boto3 psycopg2-binary
