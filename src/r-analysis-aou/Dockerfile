FROM ghcr.io/rocker-org/devcontainer/tidyverse:4.5

ARG USER=rstudio
ARG HOME=/home/$USER

COPY static /usr/lib/rstudio-server/www/aou-static
RUN sed -i 's|</head>|<script src="/aou-static/aou-policy-interceptor.js"></script><link rel="stylesheet" href="/aou-static/aou-policy-styles.css"></head>|' /usr/lib/rstudio-server/www/index.htm

# Remove sudo access
RUN rm /etc/sudoers.d/${USER}

COPY --from=load-envs --chown=$USER \
    /dist/load-env /dist/load-env.sh $HOME

RUN echo "source $HOME/load-env.sh" >> $HOME/.bashrc

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
