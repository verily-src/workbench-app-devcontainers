FROM ghcr.io/rocker-org/devcontainer/tidyverse:4.5

# Install system dependencies for scExploreR and single-cell analysis
RUN apt-get update && apt-get install -y \
    libhdf5-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libpng-dev \
    libgit2-dev \
    libfontconfig1-dev \
    libfreetype6-dev \
    libcairo2-dev \
    libglpk-dev \
    && rm -rf /var/lib/apt/lists/*

# Install BiocManager and set Bioconductor version
# R 4.5 requires Bioconductor 3.22 (auto-detected by BiocManager)
RUN R -e "install.packages('BiocManager', repos='https://cloud.r-project.org')" \
    && R -e "BiocManager::install(ask=FALSE, update=FALSE)"

# Install remotes for GitHub packages
RUN R -e "install.packages('remotes', repos='https://cloud.r-project.org')"

# Install CRAN packages required by scExploreR
RUN R -e "install.packages(c( \
    'shiny', 'shinyWidgets', 'shinydashboard', 'shinyjs', 'shinyBS', \
    'shinycssloaders', 'sortable', 'rintrojs', 'waiter', 'shinytest', 'shinymanager', \
    'colourpicker', 'DT', 'yaml', \
    'Seurat', 'dplyr', 'ggplot2', 'stringr', 'glue', 'tibble', \
    'cowplot', 'patchwork', 'gridExtra', 'RColorBrewer', 'viridisLite', \
    'ggsci', 'scales', 'svglite', \
    'reactlog', 'profvis', 'pryr', 'rlog', 'R.devices', 'rlang', 'lifecycle' \
    ), repos='https://cloud.r-project.org')"

# Install Bioconductor packages (including dependencies for SCUBA)
RUN R -e "BiocManager::install(c('HDF5Array', 'SingleCellExperiment', 'SummarizedExperiment'), ask=FALSE, update=FALSE)"

# Install GitHub dependencies
RUN R -e "remotes::install_github('immunogenomics/presto', upgrade='never')" \
    && R -e "remotes::install_github('amc-heme/SCUBA', upgrade='never')" \
    && R -e "remotes::install_github('amc-heme/scDE', upgrade='never')"

# Install scExploreR itself
RUN R -e "remotes::install_github('amc-heme/scExploreR', upgrade='never')"

# Copy startup scripts and config template into the image
COPY launch-scexplorer.R /usr/local/bin/launch-scexplorer.R
COPY config-template.yaml /usr/local/share/scexplorer/config-template.yaml
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/launch-scexplorer.R \
    && chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /usr/local/share/scexplorer

# Expose port 3838 for Shiny
EXPOSE 3838

# Set entrypoint
CMD ["/usr/local/bin/entrypoint.sh"]
