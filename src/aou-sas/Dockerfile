FROM cr.sas.com/viya-4-x64_oci_linux_2-docker/sas-analytics-pro:1.28.25-20260407.1775566536751

USER root

# Stage AoU environment loader for the startup script to install into /data.
# This must be in the Dockerfile because it references a build context (load-envs).
COPY --from=load-envs /dist/load-env /dist/load-env.sh /opt/sas/aou/

###############################################################################
# Disable SAS-internal repos (unreachable outside SAS network) and enable
# public UBI repos so packages like jq, fuse, git can be resolved.
###############################################################################
RUN dnf config-manager --set-disabled \
        crackles-epel-everything \
        sas-rhel-9-baseos sas-rhel-9-appstream sas-rhel-9-codeready \
        sas-ubi-9-baseos sas-ubi-9-appstream sas-ubi-9-codeready-builder && \
    dnf config-manager --set-enabled \
        ubi-9-baseos-rpms ubi-9-appstream-rpms ubi-9-codeready-builder-rpms

###############################################################################
# System packages required by Workbench startup scripts
###############################################################################
RUN dnf install -y --allowerasing curl fuse fuse-libs wget sudo git \
        java-17-openjdk-headless && \
    dnf clean all

###############################################################################
# Google Cloud SDK
###############################################################################
RUN curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-565.0.0-linux-x86_64.tar.gz && \
    tar -xf google-cloud-cli-565.0.0-linux-x86_64.tar.gz && \
    ./google-cloud-sdk/install.sh -q && \
    ln -sf /google-cloud-sdk/bin/* /bin/ && \
    rm -f google-cloud-cli-565.0.0-linux-x86_64.tar.gz

###############################################################################
# AoU user — a separate, unprivileged user for SAS Studio sessions.
# GID 1100 matches the original Helm chart (sasAouGroup).
###############################################################################
RUN groupadd -g 1100 aougroup && \
    useradd -g aougroup -m -d /data -s /bin/bash aou && \
    echo "aou:aou" | chpasswd && \
    rm -f /etc/sudoers.d/aou

###############################################################################
# SAS configuration
###############################################################################
RUN echo "-work /data/saswork" >> /opt/sas/viya/config/etc/workspaceserver/default/sasv9_usermods.cfg && \
    echo "-utilloc /data/utilloc" >> /opt/sas/viya/config/etc/workspaceserver/default/sasv9_usermods.cfg && \
    echo 'if [ -f /data/.aou-env ]; then source /data/.aou-env; fi' >> \
      /opt/sas/viya/config/etc/workspaceserver/default/workspaceserver_usermods.sh && \
    echo 'if [ -f /data/.workbench-env ]; then source /data/.workbench-env; fi' >> \
      /opt/sas/viya/config/etc/workspaceserver/default/workspaceserver_usermods.sh && \
    sed -Ei 's#^USERMODS=(.*)#USERMODS=-allowxcmd \1#g' \
      /opt/sas/viya/config/etc/spawner/default/spawner_usermods.sh

###############################################################################
# Apache proxy — auto-login, header cleanup, and HTTPS scheme fix
#
# ServerName https://localhost: Apache only receives HTTP (the Workbench proxy
# terminates TLS upstream), but it must still generate https:// Location
# headers in redirects (RedirectMatch, Redirect, etc.).  Without this setting,
# browsers receive http:// redirect URLs that fail behind the HTTPS proxy.
###############################################################################
RUN PROXY_CONF=/etc/httpd/conf.d/dkrapro-proxy.conf && \
    sed -i "s/RequestHeader/#RequestHeader/g" "${PROXY_CONF}" && \
    sed -i 's|^ServerName localhost$|ServerName https://localhost|' "${PROXY_CONF}" && \
    sed -i '/ProxyPreserveHost On/a # AOU-CONFIGURED' "${PROXY_CONF}" && \
    sed -i '/AOU-CONFIGURED/a RequestHeader set X-SAS-Authorization "Basic YW91OmFvdQ=="' "${PROXY_CONF}" && \
    sed -i '/AOU-CONFIGURED/a RequestHeader set X-Forwarded-Proto "https"' "${PROXY_CONF}" && \
    sed -i '/AOU-CONFIGURED/a Header unset X-Frame-Options' "${PROXY_CONF}" && \
    sed -i '/AOU-CONFIGURED/a Header unset Content-Security-Policy' "${PROXY_CONF}" && \
    sed -i '/AOU-CONFIGURED/a Header edit Set-Cookie "^(.*SameSite=None.*)\$" "\$1; Secure"' "${PROXY_CONF}"

###############################################################################
# Create /data directory and chown to AoU user. When the volume is mounted it
# will inherit the owner
###############################################################################
RUN mkdir -p /data && chown aou:aougroup /data

# SAS Studio takes ~40s to start inside the container.  The Docker
# HEALTHCHECK lets the host-level readiness probe (probe-proxy-readiness.sh)
# wait for HTTP 200 before marking startup_script/status=COMPLETE.
HEALTHCHECK --interval=5s --timeout=3s --start-period=60s --retries=3 \
  CMD curl -sf http://localhost:7080/SASStudio/ || exit 1

# Wrapper entrypoint: copies the SAS license from Mikey Secrets (if active)
# to /sasinside/ before handing off to the SAS entrypoint.
COPY --from=wb-secret-receiver /dist/wb-secret-receiver /wb-secret-receiver
COPY sas-entrypoint.sh /opt/sas/aou/sas-entrypoint.sh
RUN chmod +x /opt/sas/aou/sas-entrypoint.sh
ENTRYPOINT ["/wb-secret-receiver", "/opt/sas/aou/sas-entrypoint.sh"]
