FROM golang@sha256:ce864e7223ac17b1775e6fd0b4c0db580c2eb50e7953a427916379e4b92a1628
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/wb-secret-receiver .

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
