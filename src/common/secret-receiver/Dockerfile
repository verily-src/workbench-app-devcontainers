FROM golang@sha256:3889b425f035be855a72fb4755265311293b6d414521f0a519d819df32222d83
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/wb-secret-receiver .

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
