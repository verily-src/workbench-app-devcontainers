FROM golang@sha256:7a3e50096189ad57c9f9f865e7e4aa8585ed1585248513dc5cda498e2f41812c
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/load-env .

COPY load-env.sh /dist/load-env.sh
RUN chmod +x /dist/load-env.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
