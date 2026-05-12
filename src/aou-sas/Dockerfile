FROM cr.sas.com/viya-4-x64_oci_linux_2-docker/sas-analytics-pro:1.28.25-20260407.1775566536751

USER root

# Stage AoU environment loader for the startup script to install into /data.
# This must be in the Dockerfile because it references a build context (load-envs).
COPY --from=load-envs /dist/load-env /dist/load-env.sh /opt/sas/aou/

###############################################################################
# Package-manager compatibility
# Workbench startup scripts (post-startup.sh, resource-mount.sh) expect
# apt-get / apt.  These shims delegate to yum on this RHEL-based SAS image.
###############################################################################
RUN printf '#!/bin/bash\ncase "$1" in\n  update) exec yum makecache -y ;;\n  install) shift; exec yum install -y --allowerasing "$@" ;;\n  *) exec yum "$@" ;;\nesac\n' > /usr/local/bin/apt-get && \
    chmod +x /usr/local/bin/apt-get && \
    cp /usr/local/bin/apt-get /usr/local/bin/apt && \
    chmod +x /usr/local/bin/apt

###############################################################################
# Disable SAS-internal repos (unreachable outside SAS network) and enable
# public UBI + EPEL repos so packages like jq, fuse, git can be resolved.
###############################################################################
RUN dnf config-manager --set-disabled \
        crackles-epel-everything \
        sas-rhel-9-baseos sas-rhel-9-appstream sas-rhel-9-codeready \
        sas-ubi-9-baseos sas-ubi-9-appstream sas-ubi-9-codeready-builder && \
    dnf config-manager --set-enabled \
        ubi-9-baseos-rpms ubi-9-appstream-rpms ubi-9-codeready-builder-rpms && \
    rpm -ivh https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    yum clean all

###############################################################################
# System packages required by Workbench startup scripts
###############################################################################
RUN yum install -y --allowerasing curl fuse fuse-libs wget sudo git \
        java-17-openjdk-headless && \
    yum clean all

###############################################################################
# gcsfuse — GCS bucket mounting
###############################################################################
RUN printf '[gcsfuse]\nname=gcsfuse (packages.cloud.google.com)\nbaseurl=https://packages.cloud.google.com/yum/repos/gcsfuse-el7-x86_64\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=0\ngpgkey=https://packages.cloud.google.com/yum/doc/yum-key.gpg\n       https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg\n' > /etc/yum.repos.d/gcsfuse.repo && \
    yum install -y gcsfuse && \
    yum clean all

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

# Wrapper entrypoint: copies the SAS license from Mikey Secrets (if active)
# to /sasinside/ before handing off to the SAS entrypoint.
COPY sas-entrypoint.sh /opt/sas/aou/sas-entrypoint.sh
RUN chmod +x /opt/sas/aou/sas-entrypoint.sh
ENTRYPOINT ["/opt/sas/aou/sas-entrypoint.sh"]
