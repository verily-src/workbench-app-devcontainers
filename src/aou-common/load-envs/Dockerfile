FROM golang@sha256:91eda9776261207ea25fd06b5b7fed8d397dd2c0a283e77f2ab6e91bfa71079d
WORKDIR /source
RUN --mount=type=bind,source=.,target=/source,rw \
    mkdir -p /dist && \
    go build -v -o /dist/load-env .

COPY load-env.sh /dist/load-env.sh
RUN chmod +x /dist/load-env.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
