# Use the official NVIDIA Clara Parabricks container as the base image
FROM nvcr.io/nvidia/clara/clara-parabricks:4.5.1-1

#  Set the default shell for subsequent commands to bash.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG NB_USER=jupyter
ARG NB_UID=1010
ARG NB_GID=1000
ARG WORKDIR=/home/${NB_USER}

# Switch to root user to install packages and create new user
USER root

# This folder caused java installation issues, removing it resolves this
RUN rm -rf /var/lib/apt/lists/*

RUN \
    mkdir -p /etc/sudoers.d/ \
    # Create the user and set their shell directly in one step.
    # This avoids potential errors with 'groupadd' and makes 'chsh' redundant.
    && groupadd --gid ${NB_GID} ${NB_USER} && useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER} \
    # Grant password-less sudo access to the new user
    && echo "${NB_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${NB_USER} \
    && chmod 0440 /etc/sudoers.d/${NB_USER}

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