FROM golang@sha256:e58f92c51f4cc98f2ef4780ba8708fe914f20e6175720a19c1c85ff029a6b9fc
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/wb-secret-receiver .

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
