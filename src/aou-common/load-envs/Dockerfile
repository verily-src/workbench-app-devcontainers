FROM golang@sha256:167053a2bb901972bf2c1611f8f52c44d5fe7e762e5cab213708d82c421614db
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/load-env .

COPY load-env.sh /dist/load-env.sh
RUN chmod +x /dist/load-env.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
