# Cursor IDE Development Container
# Based on ghcr.io/linuxserver/baseimage-kasmvnc with Cursor IDE pre-installed

FROM ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm

# Cursor version to install
ARG CURSOR_VERSION=1.7.52
ARG CURSOR_BUILD_HASH=b9e5948c1ad20443a5cecba6b84a3c9b99d62582

# Display configuration
ENV DISPLAY=:1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    fuse \
    libfuse2 \
    python3.11-venv \
    python3-xdg \
    libgtk-3-0 \
    libnotify4 \
    libatspi2.0-0 \
    libsecret-1-0 \
    libnss3 \
    desktop-file-utils \
    ssh-askpass \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Download Cursor AppImage from official source
RUN curl -L -o /Cursor.AppImage \
    "https://downloads.cursor.com/production/${CURSOR_BUILD_HASH}/linux/x64/Cursor-${CURSOR_VERSION}-x86_64.AppImage" && \
    chmod a+x /Cursor.AppImage

# Set up environment variables
ENV CUSTOM_PORT="8080" \
    CUSTOM_HTTPS_PORT="8443" \
    CUSTOM_USER="" \
    PASSWORD="" \
    SUBFOLDER="" \
    TITLE="Cursor v${CURSOR_VERSION}" \
    FM_HOME="/cursor"

# Copy configuration files
COPY root/ /
COPY cursor_icon.png /cursor_icon.png

# Expose ports
EXPOSE 8080 8443

# Define volumes for persistent data
VOLUME ["/config", "/cursor"]

WORKDIR /config
