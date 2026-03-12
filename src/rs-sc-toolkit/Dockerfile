FROM lscr.io/linuxserver/code-server:4.100.3

# Install R, Python, and system dependencies
RUN apt-get update && apt-get install -y \
    r-base \
    r-base-dev \
    python3 \
    python3-pip \
    python3-venv \
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
    libgeos-dev \
    libgdal-dev \
    libproj-dev \
    libudunits2-dev \
    cmake \
    wget \
    default-jdk \
    && rm -rf /var/lib/apt/lists/*

# Install Nextflow
RUN wget -qO- https://get.nextflow.io | bash && \
    mv nextflow /usr/local/bin/ && \
    chmod +x /usr/local/bin/nextflow

# Install Snakemake via pip
RUN pip3 install --no-cache-dir snakemake

# Install SCVERSE Python packages (scanpy, anndata, scvi-tools, etc.)
RUN pip3 install --no-cache-dir \
    scanpy \
    anndata \
    scvi-tools \
    muon \
    squidpy \
    cellrank \
    scvelo

# Install R packages: BiocManager first, then Seurat and Bioconductor packages
RUN R -e "install.packages('BiocManager', repos='http://cran.rstudio.com/')"

# Install Seurat and its dependencies
RUN R -e "install.packages(c('Seurat', 'SeuratObject'), repos='http://cran.rstudio.com/')"

# Install common Bioconductor packages for single-cell analysis
RUN R -e "BiocManager::install(c( \
    'SingleCellExperiment', \
    'scater', \
    'scran', \
    'DropletUtils', \
    'edgeR', \
    'limma', \
    'DESeq2', \
    'ComplexHeatmap', \
    'dittoSeq', \
    'celldex', \
    'SingleR' \
), ask=FALSE)"

# Install additional useful R packages
RUN R -e "install.packages(c( \
    'tidyverse', \
    'ggplot2', \
    'dplyr', \
    'reshape2', \
    'pheatmap', \
    'patchwork', \
    'cowplot', \
    'viridis' \
), repos='http://cran.rstudio.com/')"
