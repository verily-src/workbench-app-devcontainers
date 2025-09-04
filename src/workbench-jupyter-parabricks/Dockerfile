# Use the official NVIDIA Clara Parabricks container as the base image
FROM nvcr.io/nvidia/clara/clara-parabricks:4.5.1-1

ARG NB_USER=jupyter
ARG NB_UID=1010
ARG NB_GID=1000
ARG WORKDIR=/home/${NB_USER}

# Switch to root user to install packages and create new user
USER root

# Update package lists and install python3, pip, and other essentials
RUN apt-get update && \
    apt-get install -y python3 python3-pip sudo && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Only create the user, not the group—GID 1000 already exists as 'ubuntu'
RUN groupadd --gid ${NB_GID} ${NB_USER} && useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER}

# Fix ownership for common dirs
RUN mkdir -p /workspace \
 && chown -R ${NB_UID}:${NB_GID} ${WORKDIR} /workspace /tmp \
 && chown -R ${NB_UID}:${NB_GID} /opt/conda || true

# Environment and working directory
ENV HOME=${WORKDIR}
WORKDIR ${WORKDIR}

ENV PATH="${WORKDIR}/.local/bin:${PATH}"
# Switch to non-root user
USER ${NB_USER}

# Install Jupyter Lab using pip
RUN pip3 install jupyterlab

# Expose the port Jupyter Lab will run on
EXPOSE 8888
# Set the entrypoint to launch Jupyter Lab
