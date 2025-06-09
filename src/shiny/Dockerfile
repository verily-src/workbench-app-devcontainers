# syntax=docker/dockerfile:1.5-labs
ARG BASE_IMAGE=rocker/shiny:4.5.0
FROM ${BASE_IMAGE}

RUN rm -rf /srv/shiny-server/index.html

COPY shiny-customized.conf /etc/shiny-server/shiny-server.conf
