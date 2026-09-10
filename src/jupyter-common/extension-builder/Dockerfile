FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/user-apps-artifacts/app-jupyter-extension-builder@sha256:e0954df8685d73872af044db0fbf73e8e1f68a0325a24918e0f81631fe69aaf7

COPY extension /extension

RUN /build.sh /extension /dist

COPY setup.sh /dist/setup.sh
RUN chmod +x /dist/setup.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
