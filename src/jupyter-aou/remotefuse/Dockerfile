FROM debian:latest

RUN apt-get update --yes && \
    apt-get install -yq --no-install-recommends \
    jq \
    openssh-server \
    sudo \
    curl \
    lsb-release \
    inotify-tools \
    wget \
    locales \
    # gcloud CLI dependencies
    apt-transport-https \
    ca-certificates \
    gnupg \
    fuse \
    # aws CLI dependencies
    libc6 \
    groff

# Install gcloud CLI and gcsfuse
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt gcsfuse-$(lsb_release -c -s) main" > /etc/apt/sources.list.d/gcsfuse.list \
    && wget -qO- https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
    && apt-get update -y \
    && apt-get install -yq --no-install-recommends google-cloud-cli gcsfuse

# Install aws CLI and goofys for s3 bucket mounting
RUN apt-get update -y \
    && apt-get install -yq --no-install-recommends awscli \
    && wget "https://github.com/kahing/goofys/releases/latest/download/goofys" -O goofys \
    && chmod +x goofys \
    && mv goofys /usr/local/bin/

COPY remotefuse /remotefuse
RUN chmod +x /remotefuse
COPY entrypoint.sh /entrypoint.sh

ENV USER=remotefuse
ENV UID=1000
ENV USER_HOME_DIR=/home/remotefuse

# Create a user with the shell set to /remotefuse. This prevents the user from
# executing any other commands
RUN useradd -l -m -d $USER_HOME_DIR \
                  -u $UID \
                  -g users \
                  -s /remotefuse $USER \
    # Hide the motd and last login message
    && touch $USER_HOME_DIR/.hushlogin \
    # Uncomment user_allow_other in the fuse.conf to enable non-root user to mount files with -o allow-other option.
    && sed -i '/user_allow_other/s/^#//g' /etc/fuse.conf

ENTRYPOINT [ "/bin/sh", "/entrypoint.sh" ]
