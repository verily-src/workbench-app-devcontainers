FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:9d43e8867963eab18df5a452824ff9f47fee88ea8fc3d5a11a2ede653120f0a5

COPY extension /extension

RUN /build.sh /extension /dist

COPY setup.sh /dist/setup.sh
RUN chmod +x /dist/setup.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
