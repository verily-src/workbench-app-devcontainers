# Workbench-compatible MDV image.
#
# The prebuilt MDV image (mdvadmin/mdv:stable) is Debian 13 (trixie) and is built
# to run the app only — it ships neither `sudo` nor the legacy `apt-key`. Verily
# Workbench's per-VM provisioning needs both:
#   * post-startup.sh runs everything via `sudo -u <user>`.
#   * gcsfuse install and the google-cloud-cli devcontainer feature call
#     `apt-key add -` (removed in trixie).
# This wrapper adds those back without touching the app itself.
FROM mdvadmin/mdv:stable

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sudo gnupg curl ca-certificates lsb-release apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# `apt-key` compatibility shim (removed in trixie). Handles both the plain
# `add -` form and the `--keyring <file> add -` form used by the gcloud feature.
COPY apt-key-shim.sh /usr/local/bin/apt-key
RUN chmod +x /usr/local/bin/apt-key

# Passwordless sudo for the app user (Workbench scripts may sudo as this user).
RUN echo 'pn ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/pn \
    && chmod 0440 /etc/sudoers.d/pn

# Restore the app's runtime user (image default).
USER pn
