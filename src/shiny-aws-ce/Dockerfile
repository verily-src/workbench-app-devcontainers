# syntax=docker/dockerfile:1.5-labs
ARG BASE_IMAGE=rocker/shiny:4.5.0
FROM ${BASE_IMAGE}

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libfontconfig1-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

# Install required R packages
RUN R -e "install.packages(c(\
    'shiny', \
    'shinydashboard', \
    'DT', \
    'plotly', \
    'dplyr', \
    'ggplot2', \
    'lubridate', \
    'scales', \
    'readr', \
    'shinycssloaders', \
    'tidyr', \
    'stringr' \
    ), repos='https://cloud.r-project.org/')"

# Remove default shiny server index
RUN rm -rf /srv/shiny-server/index.html

# Copy custom shiny server configuration
COPY shiny-customized.conf /etc/shiny-server/shiny-server.conf

# Copy the Shiny app
COPY app.R /srv/shiny-server/aws-cost-explorer/app.R

# Ensure proper permissions
RUN chown -R shiny:shiny /srv/shiny-server
