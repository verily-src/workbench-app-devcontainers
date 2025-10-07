FROM 353631943781.dkr.ecr.us-west-2.amazonaws.com/verily-cedar-small:latest

ARG NB_USER=rstudio
ARG WORKDIR=/home/${NB_USER}

# Only create the user, not the group—GID 1000 already exists as 'ubuntu'
RUN useradd --uid ${NB_UID} --gid ${NB_GID} --create-home --home-dir ${WORKDIR} --shell /bin/bash ${NB_USER} \
