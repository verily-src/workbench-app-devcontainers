FROM ghcr.io/rocker-org/devcontainer/tidyverse:4.5

# Register .wdl (Workflow Description Language) as a text MIME type so RStudio
# opens .wdl files as text instead of misidentifying them as binary (PHP-130724).
COPY wdl.xml /usr/share/mime/packages/wdl.xml
RUN update-mime-database /usr/share/mime
