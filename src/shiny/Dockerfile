# syntax=docker/dockerfile:1.5-labs
ARG VARIANT=4
ARG BASE_IMAGE=rocker/shiny
FROM ${BASE_IMAGE}:${VARIANT}

RUN rm -rf /srv/shiny-server/index.html

COPY shiny-customized.conf /etc/shiny-server/shiny-server.conf
