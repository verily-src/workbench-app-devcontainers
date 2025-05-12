FROM debian:latest

RUN apt-get update --yes && \
    apt-get install -yq --no-install-recommends \
    jq \
    openssh-server \
    sudo \
    curl \
    lsb-release \
    locales \
    # gcloud CLI dependencies
    apt-transport-https \
    ca-certificates \
    gnupg \
    fuse \
    # aws CLI dependencies
    libc6 \
    groff \
    # Install Java 17 and jq for Workbench CLI
    openjdk-17-jdk

# Install gcloud CLI and gcsfuse
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt gcsfuse-$(lsb_release -c -s) main" > /etc/apt/sources.list.d/gcsfuse.list && \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update -y && \
    apt-get install -yq --no-install-recommends google-cloud-cli gcsfuse

# Install aws CLI and goofys for s3 bucket mounting
RUN apt-get update -y && \
    apt-get install -yq --no-install-recommends awscli && \
    curl -L "https://github.com/kahing/goofys/releases/latest/download/goofys" -o goofys && \
    chmod +x goofys && \
    mv goofys /usr/local/bin/

COPY wb /wb
RUN chmod +x /wb
COPY entrypoint.sh /entrypoint.sh

ENV USER=wbcli
ENV UID=1001
ENV USER_HOME_DIR=/home/wbcli

# Create a user with the shell set to /wb. This prevents the user from executing
# any other commands
RUN useradd -l -m -d $USER_HOME_DIR \
                  -u $UID \
                  -s /wb $USER

ENTRYPOINT [ "/bin/sh", "/entrypoint.sh" ]
