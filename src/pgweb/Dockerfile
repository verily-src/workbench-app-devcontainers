FROM sosedoff/pgweb@sha256:a5256d416e2e8b92d69a4459058e3eca33a9f075d8325491644411d0bc3bd70b AS pgweb

# We extract just the pgweb binary and rebuild the rest of this Dockerfile
# ourselves so we can pin/update the base OS independently of upstream.
# TODO: remove this workaround once sosedoff/pgweb publishes an image with
# an up-to-date OS and we can go back to using it directly.
FROM debian@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132 AS keyring
ADD https://www.postgresql.org/media/keys/ACCC4CF8.asc keyring.asc
RUN apt-get update && \
    apt-get install -qq --no-install-recommends gpg
RUN gpg -o keyring.pgp --dearmor keyring.asc

FROM debian@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

USER root

ARG keyring=/usr/share/keyrings/postgresql-archive-keyring.pgp
COPY --from=keyring /keyring.pgp $keyring

# Use the official postgresql.org apt repo (rather than Debian's bundled
# packages) so we get a current postgresql-client, matching upstream:
# https://github.com/sosedoff/pgweb/blob/master/Dockerfile
RUN . /etc/os-release && \
    echo "deb [signed-by=${keyring}] http://apt.postgresql.org/pub/repos/apt/ ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
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
