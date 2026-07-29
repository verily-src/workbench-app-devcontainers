FROM ghcr.io/rocker-org/devcontainer/tidyverse@sha256:3a9ecbed900f17da528cdb17c3ddc43045fc9b4be7dbd8c61cb7b8a6439bfa6b

ARG USER=rstudio
ARG HOME=/home/$USER

COPY static /usr/lib/rstudio-server/www/aou-static
RUN sed -i 's|</head>|<script src="/aou-static/aou-policy-interceptor.js"></script><link rel="stylesheet" href="/aou-static/aou-policy-styles.css"></head>|' /usr/lib/rstudio-server/www/index.htm

# Remove sudo access
RUN rm /etc/sudoers.d/${USER}

COPY --from=load-envs --chown=$USER \
    /dist/load-env /dist/load-env.sh $HOME

RUN echo "source $HOME/load-env.sh" >> $HOME/.bashrc

# Source AoU env vars in R sessions via rsession-profile, which RStudio Server
# reads before starting each R session. Without this, variables exported in
# .bashrc are visible in the terminal but not via Sys.getenv() in R, because
# R sessions inherit from the RStudio server process rather than the shell.
RUN mkdir -p /etc/rstudio && \
    printf 'if [ -f "${HOME}/load-env.sh" ]; then\n    source "${HOME}/load-env.sh"\nfi\n' \
    > /etc/rstudio/rsession-profile

# TODO(PHP-87353): Add remotefuse back. See https://github.com/verily-src/workbench-app-devcontainers/pull/227
