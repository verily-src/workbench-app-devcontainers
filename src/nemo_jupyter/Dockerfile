FROM nvcr.io/nvidia/nemo:25.07.nemotron-nano-v2 AS base

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

# Switch to non-root user
USER ${NB_USER}

# Capture the build before granting sudo and save as the aou target
FROM base AS nemo-aou

FROM base AS nemo

# Grant password-less sudo access to the user
USER root
RUN echo "${NB_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${NB_USER} \
    && chmod 0440 /etc/sudoers.d/${NB_USER}
USER ${NB_USER}
