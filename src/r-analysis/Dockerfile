FROM 353631943781.dkr.ecr.us-west-2.amazonaws.com/verily-cedar-small:latest

# Only create the user, not the group—GID 1000 already exists as 'ubuntu'
RUN useradd --create-home --shell /bin/bash rstudio && chown -R rstudio:rstudio /home/rstudio
