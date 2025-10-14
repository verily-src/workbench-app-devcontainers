FROM golang:1.23-bookworm
WORKDIR /source
RUN --mount=type=bind,source=./load-env,target=/source/load-env,rw \
    mkdir -p /dist && \
    cd /source/load-env && \
    go build -v -o /dist/load-env .

COPY envs /dist/.envs
COPY load-env.sh /dist/load-env.sh
RUN chmod +x /dist/load-env.sh

ENTRYPOINT ["echo", "This image is only a build layer and should not be run directly."]
