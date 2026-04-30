#!/bin/bash
# sas-startup.sh — Pre-deployment setup for SAS Analytics Pro on VWB GCE.
#
# Mounted at /opt/sas/aou/sas-startup.sh and invoked via PRE_DEPLOY_SCRIPT
# before SAS services start.  The entrypoint writes PRE_DEPLOY_SCRIPT to
# /tmp/pre_deploy.sh and runs it, so we must NOT mount at that path.
#
# All steps are idempotent so container restarts are fast.

set -o errexit
set -o nounset
set -o pipefail

###############################################################################
# Package-manager compatibility
# Workbench startup scripts (post-startup.sh, resource-mount.sh) expect
# apt-get / apt.  These shims delegate to yum on this RHEL-based SAS image.
###############################################################################
if [ ! -f /usr/local/bin/apt-get ]; then
  cat > /usr/local/bin/apt-get << 'SHIM'
#!/bin/bash
case "$1" in
  update) exec yum makecache -y ;;
  install) shift; exec yum install -y "$@" ;;
  *) exec yum "$@" ;;
esac
SHIM
  chmod +x /usr/local/bin/apt-get
  cp /usr/local/bin/apt-get /usr/local/bin/apt
  chmod +x /usr/local/bin/apt
fi

###############################################################################
# System packages required by Workbench startup scripts
###############################################################################
yum install -y jq curl fuse fuse-libs tar wget sudo git 2>/dev/null || true

###############################################################################
# gcsfuse — GCS bucket mounting
###############################################################################
if ! command -v gcsfuse &>/dev/null; then
  cat > /etc/yum.repos.d/gcsfuse.repo << 'EOF'
[gcsfuse]
name=gcsfuse (packages.cloud.google.com)
baseurl=https://packages.cloud.google.com/yum/repos/gcsfuse-el7-x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=https://packages.cloud.google.com/yum/doc/yum-key.gpg
       https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
EOF
  yum install -y gcsfuse || true
fi

###############################################################################
# Google Cloud SDK
###############################################################################
if ! command -v gcloud &>/dev/null; then
  curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-565.0.0-linux-x86_64.tar.gz \
    && tar -xf google-cloud-cli-565.0.0-linux-x86_64.tar.gz \
    && ./google-cloud-sdk/install.sh -q \
    && ln -sf /google-cloud-sdk/bin/* /bin/ \
    && rm -f google-cloud-cli-565.0.0-linux-x86_64.tar.gz \
    || true
fi

###############################################################################
# AoU user (non-root, no sudo)
###############################################################################
AOU_GID=${AOU_GID:-1001}
groupadd -f -g "${AOU_GID}" aougroup
id aou &>/dev/null || useradd -g aougroup -m -d /data -s /bin/bash aou
echo "aou:aou" | chpasswd
rm -f /etc/sudoers.d/aou

###############################################################################
# Data directories (on the sas-data volume)
###############################################################################
mkdir -p /data/saswork /data/utilloc
chown -R aou:aougroup /data

###############################################################################
# AoU environment loader (staged in Dockerfile at /opt/sas/aou/)
###############################################################################
if [ -d /opt/sas/aou ]; then
  cp -n /opt/sas/aou/load-env /opt/sas/aou/load-env.sh /data/ 2>/dev/null || true
  chown aou:aougroup /data/load-env /data/load-env.sh 2>/dev/null || true
  grep -q "load-env.sh" /data/.bashrc 2>/dev/null || \
    echo "source /data/load-env.sh" >> /data/.bashrc
fi

###############################################################################
# SAS configuration
###############################################################################
USERMODS_CFG=/opt/sas/viya/config/etc/workspaceserver/default/sasv9_usermods.cfg
grep -q "saswork" "${USERMODS_CFG}" 2>/dev/null || \
  echo "-work /data/saswork" >> "${USERMODS_CFG}"
grep -q "utilloc" "${USERMODS_CFG}" 2>/dev/null || \
  echo "-utilloc /data/utilloc" >> "${USERMODS_CFG}"

sed -Ei 's#^USERMODS=(.*)#USERMODS=-allowxcmd \1#g' \
  /opt/sas/viya/config/etc/spawner/default/spawner_usermods.sh

###############################################################################
# Apache proxy — auto-login and header cleanup
###############################################################################
PROXY_CONF=/etc/httpd/conf.d/dkrapro-proxy.conf

# Comment out default RequestHeader lines from the SAS image, then re-add
# exactly the ones we need.  Use a marker so restarts are idempotent.
if ! grep -q "AOU-CONFIGURED" "${PROXY_CONF}"; then
  sed -i "s/RequestHeader/#RequestHeader/g" "${PROXY_CONF}"

  # Force Apache to generate https:// URLs in redirects (RedirectMatch etc.)
  # since the Workbench proxy terminates TLS upstream.
  sed -i 's|^ServerName localhost$|ServerName https://localhost|' "${PROXY_CONF}"

  sed -i '/ProxyPreserveHost On/a # AOU-CONFIGURED' "${PROXY_CONF}"

  # Auto-login (base64 of "aou:aou" = YW91OmFvdQ==)
  sed -i '/AOU-CONFIGURED/a RequestHeader set X-SAS-Authorization "Basic YW91OmFvdQ=="' \
    "${PROXY_CONF}"
  sed -i '/AOU-CONFIGURED/a RequestHeader set X-Forwarded-Proto "https"' \
    "${PROXY_CONF}"

  # Strip framing restrictions so SAS Studio can be iframed by the Workbench UI.
  sed -i '/AOU-CONFIGURED/a Header unset X-Frame-Options' \
    "${PROXY_CONF}"
  sed -i '/AOU-CONFIGURED/a Header unset Content-Security-Policy' \
    "${PROXY_CONF}"

  # SameSite=None cookies require the Secure flag.  The app sees HTTP
  # (proxy terminates TLS) so SAS omits it — add it via Apache.
  sed -i '/AOU-CONFIGURED/a Header edit Set-Cookie "^(.*SameSite=None.*)$" "$1; Secure"' \
    "${PROXY_CONF}"
fi
