# Based on https://github.com/Arfo-du-blo/cursor-in-browser (MIT License)
# Vendored here for security and version control; no runtime dependency on community image.

FROM ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm

ARG CURSOR_VERSION=1.7.52
ARG CURSOR_BUILD_HASH=b9e5948c1ad20443a5cecba6b84a3c9b99d62582

ENV DISPLAY=:1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl fuse libfuse2 \
        python3.11-venv python3-xdg \
        libgtk-3-0 libnotify4 libatspi2.0-0 libsecret-1-0 libnss3 \
        desktop-file-utils fonts-noto-color-emoji \
        git ssh-askpass && \
    apt-get autoclean && \
    rm -rf /var/lib/apt/lists/* /var/tmp/* /tmp/*

RUN curl -fL \
    "https://downloads.cursor.com/production/${CURSOR_BUILD_HASH}/linux/x64/Cursor-${CURSOR_VERSION}-x86_64.AppImage" \
    -o /Cursor.AppImage && \
    chmod a+x /Cursor.AppImage

ENV CUSTOM_PORT="8080" \
    CUSTOM_HTTPS_PORT="8443" \
    CUSTOM_USER="" \
    PASSWORD="" \
    SUBFOLDER="" \
    TITLE="Cursor v${CURSOR_VERSION}" \
    FM_HOME="/cursor"

COPY root/ /
COPY cursor_icon.png /cursor_icon.png

EXPOSE 8080 8443
VOLUME ["/config", "/cursor"]
