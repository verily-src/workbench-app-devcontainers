FROM vllm/vllm-openai:latest AS base

ARG NB_USER=vllm
ARG NB_UID=1010
ARG NB_GID=1000
ARG WORKDIR=/home/${NB_USER}

USER root

RUN apt-get update \
    && apt-get install -yq sudo curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid ${NB_GID} ${NB_USER} || true \
    && useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER} \
    && mkdir -p /workspace /models \
    && chown -R ${NB_UID}:${NB_GID} ${WORKDIR} /workspace /models /tmp

# Grant passwordless sudo
RUN echo "${NB_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${NB_USER} \
    && chmod 0440 /etc/sudoers.d/${NB_USER}

ENV HOME=${WORKDIR}
WORKDIR ${WORKDIR}

USER ${NB_USER}
