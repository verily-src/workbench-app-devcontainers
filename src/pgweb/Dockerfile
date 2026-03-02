FROM sosedoff/pgweb

USER root

RUN apt-get update && \
    apt-get -y install sudo && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/*

USER pgweb
