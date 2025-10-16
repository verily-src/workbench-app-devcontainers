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
RUN pip3 install jupyterlab && \
    # Install NVIDIA Rapids
    pip3 install \
        --extra-index-url=https://pypi.nvidia.com \
        "cudf-cu12==25.8.*" \
        "dask-cudf-cu12==25.8.*" \
        "cuml-cu12==25.8.*" \
        "cugraph-cu12==25.8.*" \
        "nx-cugraph-cu12==25.8.*" \
        "cuxfilter-cu12==25.8.*" \
        "cucim-cu12==25.8.*" \
        "pylibraft-cu12==25.8.*" \
        "raft-dask-cu12==25.8.*" \
        "cuvs-cu12==25.8.*" \
        "nx-cugraph-cu12==25.8.*"

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

COPY --from=extension-builder --chown=${NB_UID}:${NB_GID} \
    /dist/snippets $WORKDIR/.local/share/jupyter/snippets

USER root

# Install all extensions we built
RUN --mount=type=bind,from=extension-builder,source=/dist,target=/tmp/extensions \
    /tmp/extensions/setup.sh

COPY --from=load-envs --chown=$JUPYTER_USER \
    /dist/load-env /dist/load-env.sh $HOME

RUN echo "source $HOME/load-env.sh" >> $HOME/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227

USER ${NB_USER}

### END parabricks-aou ###
