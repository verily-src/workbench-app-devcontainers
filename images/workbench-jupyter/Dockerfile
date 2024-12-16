# Use latest CUDA base image that supports both Pytorch and TensorFlow
# Source: https://hub.docker.com/layers/nvidia/cuda/11.8.0-cudnn8-runtime-ubuntu22.04/images/sha256-f6913f3c02f297877f6859d12ff330043c0be668fdad86868c29a239a5a82151
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Fix: https://github.com/hadolint/hadolint/wiki/DL4006
# Fix: https://github.com/koalaman/shellcheck/wiki/SC3014
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

#########################
# Environment Variables #
#########################
ENV DEBIAN_FRONTEND noninteractive
ENV LC_ALL en_US.UTF-8

ENV PYTHON_VERSION 3.10

###############################
# Install System Dependencies #
###############################

USER root

# Install system dependencies
RUN apt-get update --yes && \
    apt-get install -yq --no-install-recommends \
    # basic necessities
    locales \
    aria2 \
    bzip2 \
    curl \
    jq \
    lsb-release \
    nano \
    procps \
    tree \
    unzip \
    vim \
    sudo \
    wget \
    # R requirements
    less \
    # gcloud CLI dependencies
    apt-transport-https \
    ca-certificates \
    gnupg \
    # aws CLI dependencies
    # > debian names glibc as libc6
    libc6 \
    groff \
    # gcc compiler
    build-essential \
    locales \
    # for ssh-agent and ssh-add
    keychain \
    # git
    git \
    openssh-client \
    # Enable clipboard
    xclip \
    # Python dependencies
    software-properties-common

# Add deadsnakes PPA for python
RUN sudo add-apt-repository ppa:deadsnakes/ppa

# Install python
RUN apt-get update --yes && \
    apt-get install -yq --no-install-recommends \
    "python${PYTHON_VERSION}" \
    "python${PYTHON_VERSION}-venv" \
    "python${PYTHON_VERSION}-distutils"

# Set the default python version
RUN update-alternatives --install /usr/bin/python3 python3 "/usr/bin/python${PYTHON_VERSION}" 1

# Generate locales
# Then install texlive (latex), dependency for nbconvert
    # https://nbconvert.readthedocs.io/en/latest/install.html#installing-tex
RUN locale-gen en_US.UTF-8 \
    && apt-get install -yq \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-plain-generic

# Install Node >18 (needed for jupyterlab)
RUN apt-get update && apt-get install -yq --no-install-recommends
RUN mkdir -p /etc/apt/keyrings
RUN curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg

RUN echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_18.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list
RUN apt-get update && apt-get install -f -yq nodejs

# Install Java 17 for Workbench CLI
RUN apt-get update -y \
    && apt-get install -yq openjdk-17-jdk

# Install gcloud CLI
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update -y && \
    apt-get install -y google-cloud-cli

# Install aws CLI
RUN apt-get install -yq awscli

# Clean up the apt cache
RUN apt-get clean \
    && rm -rf /var/lib/apt/lists/*

###############
# Users Setup #
###############

ENV JUPYTER_USER jupyter
ENV JUPYTER_UID 1000
ENV JUPYTER_USER_HOME_DIR /home/$JUPYTER_USER

# Create the Jupyter user with /bin/bash as the default shell
RUN useradd -m -d $JUPYTER_USER_HOME_DIR -N -u $JUPYTER_UID -g users -s /bin/bash $JUPYTER_USER
# Grant sudo privileges to the Jupyter user
RUN echo "$JUPYTER_USER ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/$JUPYTER_USER \
    && chmod 0440 /etc/sudoers.d/$JUPYTER_USER

###########################
# Install python packages #
###########################

RUN python3 -m venv /venv
RUN curl -O https://bootstrap.pypa.io/get-pip.py && \
    python3 get-pip.py && \
    rm get-pip.py

# Install Python dependencies
RUN python3 -m pip install \
    numpy==1.26.0 \
    pandas==2.2.1 \
    matplotlib==3.9.0 \
    jupyterlab==4.3.1 \
    ipykernel==6.29.5 \
    bigquery_jupyter_plugin==0.0.1

# Install PyTorch, TorchVision, and TorchAudio with CUDA 11.8 support, but do
# not include CUDA libraries as they are already provided by the base image.
RUN pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 \
    --index-url https://download.pytorch.org/whl/cu118 \
    --no-deps

# Install TensorFlow with CUDA 11.8 support
RUN python3 -m pip install \
    tensorflow==2.14.0

# Configure CUDA library paths
RUN sudo ln -s /usr/local/cuda-11.8 /usr/local/cuda \
    && ldconfig

# Install jupyterlab extensions
RUN python3 -m pip install \
    jupyterlab-git==0.50.2 \
    ipywidgets==8.1.5 \
    jupyterlab-widgets==3.0.13 \
    jupytext==1.16.4 \
    pygments==2.18.0 \
    nbdime==4.0.2

# Clean up the pip cache
RUN rm -rf /root/.cache/pip

######################################
# Configure Jupyter Server and Start #
######################################

# Set the Jupyter configuration directory
ENV JUPYTER_CONFIG_DIR $JUPYTER_USER_HOME_DIR/.jupyter
RUN mkdir -p $JUPYTER_CONFIG_DIR
COPY jupyter_server_config.py $JUPYTER_CONFIG_DIR

# Make sure the JUPYTER_USER owns the home directory
RUN chown -R $JUPYTER_USER:users $JUPYTER_USER_HOME_DIR

# Set the working directory to the user's home directory
USER $JUPYTER_USER
WORKDIR $JUPYTER_USER_HOME_DIR

# Copy the `container-post-startup-hook.sh` script to the user's home directory
COPY container-post-startup-hook.sh "${JUPYTER_USER_HOME_DIR}/.workbench/container-post-startup-hook.sh"

# Expose the application port and execute the `container-post-startup-hook.sh` script
# to start the Jupyter server
# The jupyter server will via the `container-post-startup-hook.sh` script
EXPOSE 8888
ENTRYPOINT ["/bin/bash", "-c", "${JUPYTER_USER_HOME_DIR}/.workbench/container-post-startup-hook.sh"]