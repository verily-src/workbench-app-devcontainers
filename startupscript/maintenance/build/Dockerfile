FROM ubuntu:24.04@sha256:f610ab94648195aa356059f5b41d6085c9d4d903c072430cdd1af7bdb646106b

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl jq openssl squashfs-tools=1:4.6.1-1build1 \
    && rm -rf /var/lib/apt/lists/*
COPY assemble-image.sh /usr/local/bin/assemble-image
ENTRYPOINT ["/usr/local/bin/assemble-image"]
