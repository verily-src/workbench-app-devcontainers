FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:3cd735e8f4df98984ee9673cb34b0cd2b1069c28f403167a37480b580af299dc

COPY extension /extension

RUN /build.sh /extension /dist

COPY setup.sh /dist/setup.sh
RUN chmod +x /dist/setup.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
