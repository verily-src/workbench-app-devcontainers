FROM us-west2-docker.pkg.dev/shared-pub-buckets-94mvrf/workbench-artifacts/app-jupyter-extension-builder@sha256:d91b0fe5b7864b4a79a5a4bdddf4475de71c5e5dfa6f03827edb5e426bc7a455

COPY extension /extension

RUN /build.sh /extension /dist

COPY setup.sh /dist/setup.sh
RUN chmod +x /dist/setup.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
