FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:32f6f8192a0a0a34881491600a2482608e9133ffd6fb3ff137fe65c9bc160437

COPY extension /extension

RUN /build.sh /extension /dist

COPY setup.sh /dist/setup.sh
RUN chmod +x /dist/setup.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
