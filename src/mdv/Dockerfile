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
#
# Pinned to the digest `mdvadmin/mdv:stable` pointed to on 2026-11-10 (image built 2026-03-23)
# so rebuilds are reproducible. start.sh runs this image's `poetry run gunicorn`; newer MDV
# images use `uv run` instead, so update start.sh when moving the pin forward.
FROM mdvadmin/mdv:stable@sha256:f910be7a30f8e86f7a4476d0d0c88e08145afdfbe745333f3e8f6b60c347c29a

USER root

# tabix (htslib) lets `mdvtools convert-vcf` build the genome browser track for the large sample.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sudo gnupg curl ca-certificates lsb-release apt-transport-https \
        fuse3 nginx-light gettext-base tabix \
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

# Same-origin nginx proxy that adds Document-Isolation-Policy so
# SharedArrayBuffer/WASM threads work (BENCH-9901). Runs MDV's own gunicorn
# on loopback:5056 and proxies 5055 (Workbench's expected port) through
# nginx instead. nginx runs as `pn`, so its pid/temp paths live under /tmp.
COPY nginx.conf.template /opt/mdv-nginx/nginx.conf.template
COPY start.sh /opt/mdv-nginx/start.sh
RUN chmod +x /opt/mdv-nginx/start.sh

# Workspace data sync: makes workspace bucket data available in MDV's projects directory
# (/app/mdv), and falls back to sample projects when the workspace has no MDV data. Started by
# postStartCommand after the buckets are mounted; see workspace-sync/start-workspace-sync.sh.
COPY workspace-sync/ /opt/mdv-workbench/
RUN chmod 0755 /opt/mdv-workbench/*.sh /opt/mdv-workbench/*.py \
    && mkdir -p /var/lib/mdv-workspace-sync /var/lib/mdv-samples /mnt/mdv-workspace-ro \
    && chown pn:pn /var/lib/mdv-workspace-sync /var/lib/mdv-samples

# Built-in sample, available without network access at runtime: pbmc3k_processed, the dataset in
# MDV's quickstart and Scanpy tutorial (2,638 cells x 1,838 genes).
RUN mkdir -p /opt/mdv-samples \
    && cd /tmp \
    && /app/python/.venv/bin/python -W ignore -c "import scanpy as sc; from mdvtools.conversions import convert_scanpy_to_mdv; convert_scanpy_to_mdv('/opt/mdv-samples/pbmc3k-processed', sc.datasets.pbmc3k_processed())" \
    && printf '%s\n' '# Sample: PBMC 3k (processed)' '' \
        'pbmc3k_processed from Scanpy (2,638 peripheral blood mononuclear cells x 1,838 genes), the dataset used in the MDV quickstart and Scanpy tutorial.' '' \
        'This sample is shown because no workspace bucket has an `mdv/` folder. Add your data to `<bucket>/mdv/projects/` or `<bucket>/mdv/data/` and it replaces the samples automatically.' \
        > /opt/mdv-samples/pbmc3k-processed/README.md \
    && touch /opt/mdv-samples/pbmc3k-processed/.mdv-sample-complete \
    && rm -rf /tmp/data \
    && chmod -R a+rX /opt/mdv-samples

# Restore the app's runtime user (image default).
USER pn

CMD ["/opt/mdv-nginx/start.sh"]
