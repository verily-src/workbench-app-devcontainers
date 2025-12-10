ARG CONTAINER_IMAGE=debian:bullseye
FROM $CONTAINER_IMAGE

# Install jupyter extensions
RUN --mount=type=bind,from=jupyter-extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh
