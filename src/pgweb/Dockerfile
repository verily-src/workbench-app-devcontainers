FROM sosedoff/pgweb@sha256:a5256d416e2e8b92d69a4459058e3eca33a9f075d8325491644411d0bc3bd70b AS pgweb

# We extract just the pgweb binary and rebuild the rest of this Dockerfile
# ourselves so we can pin/update the base OS independently of upstream.
# TODO: remove this workaround once sosedoff/pgweb publishes an image with
# an up-to-date OS and we can go back to using it directly.
FROM debian@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

USER root

RUN apt-get update && \
    apt-get -y install --no-install-recommends \
        ca-certificates \
        curl \
        netcat-openbsd \
        openssl \
        postgresql-client \
        sudo && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --uid 1000 --no-create-home --shell /bin/false pgweb && \
    mkdir -p /pgweb && \
    chown pgweb:pgweb /pgweb

COPY --from=pgweb /usr/bin/pgweb /usr/bin/pgweb

USER pgweb

EXPOSE 8081

ENTRYPOINT ["/usr/bin/pgweb", "--bind=0.0.0.0", "--listen=8081"]
