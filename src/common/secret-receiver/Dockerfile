FROM golang@sha256:f85330846cde1e57ca9ec309382da3b8e6ae3ab943d2739500e08c86393a21b1
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/wb-secret-receiver .

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
