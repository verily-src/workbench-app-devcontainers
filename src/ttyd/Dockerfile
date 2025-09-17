
FROM ubuntu:24.04

ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55

# Install minimal build dependencies, fuse, tmux, and ttyd
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    fuse \
    sudo \
    tmux \
    wget

# To use FUSE mounts, the container must be run with:
#   --cap-add SYS_ADMIN --device /dev/fuse

# Install ttyd
RUN wget https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64 -O /usr/local/bin/ttyd && \
    echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c - && \
    chmod +x /usr/local/bin/ttyd

# Create generic user 'workstation'
RUN useradd -m -s /bin/bash workstation && \
    echo 'workstation ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

# Switch to non-root user
USER workstation
WORKDIR /home/workstation

# Expose ttyd port
EXPOSE 3000

# Start ttyd with bash shell and writable mode
CMD ["ttyd", "-p", "3000", "--writable", "bash"]
