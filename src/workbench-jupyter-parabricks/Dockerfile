# Use the official NVIDIA Clara Parabricks container as the base image
FROM nvcr.io/nvidia/clara/clara-parabricks:4.5.1-1 AS base

#  Set the default shell for subsequent commands to bash.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG NB_USER=jupyter
ARG NB_UID=1010
ARG NB_GID=1000
ARG WORKDIR=/home/${NB_USER}

# Switch to root user to install packages and create new user
USER root

# Install sudo
RUN apt-get update \
    && apt-get install -yq sudo \
    && rm -rf /var/lib/apt/lists/*

# Create the user and set their shell directly in one step.
# This avoids potential errors with 'groupadd' and makes 'chsh' redundant.
RUN groupadd --gid ${NB_GID} ${NB_USER} \
    && useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER} \
    # Fix ownership for common dirs
    && mkdir -p /workspace \
    && chown -R ${NB_UID}:${NB_GID} ${WORKDIR} /workspace /tmp \
    && chown -R ${NB_UID}:${NB_GID} /opt/conda || true

# Environment and working directory
ENV HOME=${WORKDIR}
WORKDIR ${WORKDIR}

ENV PATH="${WORKDIR}/.local/bin:${PATH}"
# Switch to non-root user
USER ${NB_USER}
ENV SHELL=/bin/bash

# Install Jupyter Lab using pip
RUN pip3 install jupyterlab

### BEGIN parabricks ###

FROM base as parabricks

# Grant password-less sudo access to the user
USER root
RUN echo "${NB_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${NB_USER} \
    && chmod 0440 /etc/sudoers.d/${NB_USER}
USER ${NB_USER}

### END parabricks ###

### BEGIN parabricks-aou ###

FROM base AS parabricks-aou

USER root

COPY --from=extension-builder /dist/snippets $WORKDIR/.local/share/jupyter/snippets

# Install all extensions we built
RUN --mount=type=bind,from=extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227

USER ${NB_USER}

### END parabricks-aou ###
