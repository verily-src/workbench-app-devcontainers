FROM golang@sha256:3889b425f035be855a72fb4755265311293b6d414521f0a519d819df32222d83
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/load-env .

COPY load-env.sh /dist/load-env.sh
RUN chmod +x /dist/load-env.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
