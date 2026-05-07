FROM cr.sas.com/viya-4-x64_oci_linux_2-docker/sas-analytics-pro:1.28.25-20260407.1775566536751

USER root

# Stage AoU environment loader for the startup script to install into /data.
# This must be in the Dockerfile because it references a build context (load-envs).
COPY --from=load-envs /dist/load-env /dist/load-env.sh /opt/sas/aou/

# Wrapper entrypoint: copies the SAS license from Mikey Secrets (if active)
# to /sasinside/ before handing off to the SAS entrypoint.
COPY sas-entrypoint.sh /opt/sas/aou/sas-entrypoint.sh
RUN chmod +x /opt/sas/aou/sas-entrypoint.sh
ENTRYPOINT ["/opt/sas/aou/sas-entrypoint.sh"]
