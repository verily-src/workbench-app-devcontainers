FROM sosedoff/pgweb@sha256:a5256d416e2e8b92d69a4459058e3eca33a9f075d8325491644411d0bc3bd70b

USER root

RUN apt-get update && \
    apt-get -y install sudo && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /pgweb && \
    chown pgweb:pgweb /pgweb

USER pgweb
