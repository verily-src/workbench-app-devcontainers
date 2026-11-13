FROM golang@sha256:87c65a688975c0b1d4585d204874c45ca78354670e3a5f11368c5a492303d696
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/wb-secret-receiver .

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
