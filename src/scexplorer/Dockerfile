# syntax=docker/dockerfile:1.5-labs
ARG BASE_IMAGE=rocker/shiny:4.5.0
FROM ${BASE_IMAGE}

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libfontconfig1-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev \
    libhdf5-dev \
    libgit2-dev \
    libgsl-dev \
    cmake \
    libglpk-dev \
    git \
    python3 \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages for Anndata support
RUN pip3 install --no-cache-dir --break-system-packages \
    numpy \
    pandas \
    scipy \
    anndata \
    scanpy

# Install BiocManager and remotes first
RUN R -e "install.packages(c('BiocManager', 'remotes'), repos='https://cloud.r-project.org/')"

# Install Bioconductor dependencies
RUN R -e "BiocManager::install(c('HDF5Array', 'SingleCellExperiment'), ask=FALSE)"

# Install core R package dependencies
RUN R -e "install.packages(c(\
    'shiny', \
    'shinydashboard', \
    'shinyWidgets', \
    'shinyBS', \
    'shinyjs', \
    'rintrojs', \
    'waiter', \
    'Seurat', \
    'dplyr', \
    'tibble', \
    'ggplot2', \
    'ggsci', \
    'cowplot', \
    'patchwork', \
    'RColorBrewer', \
    'viridisLite', \
    'pryr', \
    'yaml', \
    'reticulate', \
    'Matrix', \
    'igraph' \
    ), repos='https://cloud.r-project.org/')"

# Install remote GitHub dependencies
RUN R -e "remotes::install_github('immunogenomics/presto')"
RUN R -e "remotes::install_github('amc-heme/SCUBA')"
RUN R -e "remotes::install_github('amc-heme/scDE')"

# Install scExploreR from GitHub at v1.0.0
RUN R -e "remotes::install_github('amc-heme/scExploreR@v1.0.0')"

# Remove default shiny server index
RUN rm -rf /srv/shiny-server/index.html

# Copy custom shiny server configuration
COPY shiny-customized.conf /etc/shiny-server/shiny-server.conf

# Create app directory
RUN mkdir -p /srv/shiny-server/scexplorer

# Copy the startup script that will launch scExploreR
COPY app.R /srv/shiny-server/scexplorer/app.R

# Create data directory for user objects
RUN mkdir -p /srv/shiny-server/scexplorer/data && \
    chown -R shiny:shiny /srv/shiny-server
