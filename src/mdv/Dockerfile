# Workbench-compatible MDV image.
#
# The prebuilt MDV image (mdvadmin/mdv:stable) is Debian 13 (trixie) and is built
# to run the app only — it ships neither `sudo` nor the legacy `apt-key`. Verily
# Workbench's per-VM provisioning needs both:
#   * post-startup.sh runs everything via `sudo -u <user>`.
#   * gcsfuse install and the google-cloud-cli devcontainer feature call
#     `apt-key add -` (removed in trixie).
#   * post-startup.sh unconditionally `apt-get install`s `fuse`, which trixie
#     renamed to `fuse3` (no `fuse` candidate exists).
# This wrapper adds those back without touching the app itself.
FROM mdvadmin/mdv:stable

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sudo gnupg curl ca-certificates lsb-release apt-transport-https \
        fuse3 \
    && rm -rf /var/lib/apt/lists/*

# trixie renamed the `fuse` package to `fuse3`. Workbench's post-startup.sh runs
# `apt-get install -y ... fuse`, which has no candidate here and would abort the
# provisioning hook. Register a dummy `fuse` package (depending on the real
# fuse3) so that install resolves to "already the newest version" and succeeds.
# The version must be >= 3.17.2-3: fuse3 declares `Conflicts: fuse (<< 3.17.2-3)`.
RUN mkdir -p /tmp/fuse-shim/DEBIAN \
    && printf 'Package: fuse\nVersion: 3.17.2-3\nArchitecture: all\nMaintainer: verily-workbench <noreply@verily.com>\nDepends: fuse3\nDescription: Transitional shim for the legacy fuse package name on Debian trixie.\n' \
        > /tmp/fuse-shim/DEBIAN/control \
    && dpkg-deb --build /tmp/fuse-shim /tmp/fuse.deb \
    && dpkg -i /tmp/fuse.deb \
    && rm -rf /tmp/fuse-shim /tmp/fuse.deb

# `apt-key` compatibility shim (removed in trixie). Handles both the plain
# `add -` form and the `--keyring <file> add -` form used by the gcloud feature.
COPY apt-key-shim.sh /usr/local/bin/apt-key
RUN chmod +x /usr/local/bin/apt-key

# Passwordless sudo for the app user (Workbench scripts may sudo as this user).
RUN echo 'pn ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/pn \
    && chmod 0440 /etc/sudoers.d/pn

# Restore the app's runtime user (image default).
USER pn
