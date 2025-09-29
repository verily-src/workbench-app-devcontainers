FROM nvcr.io/nvidia/rapidsai/notebooks:25.08-cuda12.9-py3.13 as base

#######################################################
# Base container setup - user creation and permissions
#######################################################

ARG NB_USER=jupyter
ARG NB_UID=1010
ARG NB_GID=1000
ARG WORKDIR=/home/${NB_USER}

USER root

# Install sudo
RUN apt-get update \
    && apt-get install -yq sudo \
    && rm -rf /var/lib/apt/lists/*

# Only create the user, not the group—GID 1000 already exists as 'ubuntu'
RUN useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER} \
    # Fix ownership for common dirs
    && mkdir -p /workspace \
    && chown -R ${NB_UID}:${NB_GID} ${WORKDIR} /workspace /tmp \
    && chown -R ${NB_UID}:${NB_GID} /opt/conda || true \
    # Add alias for weightsbiases
    && printf 'alias weightsbiases="/usr/local/bin/wb"\nalias wb="/usr/bin/wb"\n' >> ${WORKDIR}/.bashrc

# Environment and working directory
ENV HOME=${WORKDIR}
WORKDIR ${WORKDIR}

# Switch to non-root user for base image completion
USER ${NB_USER}

##############################################
# RAPIDS-specific customizations
##############################################

FROM base as rapids

USER root

# Grant password-less sudo access to the user
RUN echo "${NB_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${NB_USER} \
    && chmod 0440 /etc/sudoers.d/${NB_USER}

##############################################
# Python package installation for scRNA-seq
##############################################

# Install additional Python packages for single-cell RNA analysis
RUN pip install --no-cache-dir \
    anndata==0.11.4 \
    array-api-compat==1.12.0 \
    contourpy==1.3.2 \
    cycler==0.12.1 \
    fonttools==4.58.0 \
    h5py==3.13.0 \
    imageio==2.37.0 \
    joblib==1.5.1 \
    kiwisolver==1.4.8 \
    lazy-loader==0.4 \
    legacy-api-wrap==1.4.1 \
    llvmlite==0.44.0 \
    matplotlib==3.10.3 \
    natsort==8.4.0 \
    networkx==3.4.2 \
    numba==0.61.2 \
    numpy==2.2.6 \
    pandas==2.2.3 \
    patsy==1.0.1 \
    pillow==11.2.1 \
    pynndescent==0.5.13 \
    rapids-singlecell==0.12.6 \
    scanpy==1.11.1 \
    scikit-learn==1.5.2 \
    scikit-image==0.25.2 \
    scikit-misc==0.5.1 \
    scipy==1.15.3 \
    seaborn==0.13.2 \
    session-info2==0.1.2 \
    statsmodels==0.14.4 \
    threadpoolctl==3.6.0 \
    tifffile==2025.5.10 \
    tqdm==4.67.1 \
    tzdata==2025.2 \
    umap-learn==0.5.7 \
    wget==3.2 \
    deprecated==1.2.18 \
    numcodecs==0.15.1 \
    wrapt==1.17.2 \
    zarr==2.18.7 \
    filelock==3.19.1 \
    mpmath==1.3.0 \
    nvidia-cublas-cu12==12.8.4.1 \
    nvidia-cuda-cupti-cu12==12.8.90 \
    nvidia-cuda-nvrtc-cu12==12.8.93 \
    nvidia-cuda-runtime-cu12==12.8.90 \
    nvidia-cudnn-cu12==9.10.2.21 \
    nvidia-cufft-cu12==11.3.3.83 \
    nvidia-cufile-cu12==1.13.1.3 \
    nvidia-curand-cu12==10.3.9.90 \
    nvidia-cusolver-cu12==11.7.3.90 \
    nvidia-cusparse-cu12==12.5.8.93 \
    nvidia-cusparselt-cu12==0.7.1 \
    nvidia-nccl-cu12==2.27.3 \
    nvidia-nvjitlink-cu12==12.8.93 \
    nvidia-nvtx-cu12==12.8.90 \
    sympy==1.14.0 \
    torch==2.8.0 \
    triton==3.4.0

# Switch back to non-root user for final configuration
USER ${NB_USER}

# (Optional) Install any additional dependencies here
# RUN apt-get update && apt-get install -y <package-name>

# (Optional) Copy local files into the container
# COPY . /workspace


