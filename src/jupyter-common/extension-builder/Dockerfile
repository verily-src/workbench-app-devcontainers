FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:0ddb5398887dd5fdb2456165344f5fd4cc80e3047d2a126af0b31a71b4a3e5b1

COPY extension /extension

RUN /build.sh /extension /dist

COPY setup.sh /dist/setup.sh
RUN chmod +x /dist/setup.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
