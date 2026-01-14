FROM ghcr.io/rocker-org/devcontainer/tidyverse:4.5 AS base

ENV DISABLE_AUTH=true

# TODO REMOVE ME
RUN echo "www-root-path=/{{.AppName}}/" >> /etc/rstudio/disable_auth_rserver.conf

ARG USER=rstudio

### BEGIN r-analysis ###

FROM base AS r-analysis

# Password-less sudo is already granted in the base image

### END r-analysis ###

### BEGIN r-analysis-aou ###

FROM base AS r-analysis-aou

RUN rm /etc/sudoers.d/${USER}

COPY --from=load-envs --chown=$NB_USER \
    /dist/load-env /dist/load-env.sh $HOME

RUN echo "source $HOME/load-env.sh" >> $HOME/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227

### END r-analysis-aou ###
