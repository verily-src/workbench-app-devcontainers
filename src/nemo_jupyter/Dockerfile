FROM nvcr.io/nvidia/nemo:25.07.nemotron-nano-v2

ARG NB_USER=jupyter
ARG NB_UID=1010
ARG NB_GID=1000
ARG WORKDIR=/home/${NB_USER}

USER root

# Only create the user, not the group—GID 1000 already exists as 'ubuntu'
RUN useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER}

# Fix ownership for common dirs
RUN mkdir -p /workspace \
 && chown -R ${NB_UID}:${NB_GID} ${WORKDIR} /workspace /tmp \
 && chown -R ${NB_UID}:${NB_GID} /opt/conda || true

# Environment and working directory
ENV HOME=${WORKDIR}
WORKDIR ${WORKDIR}

# Switch to non-root user
USER ${NB_USER}