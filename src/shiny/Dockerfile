# syntax=docker/dockerfile:1.5-labs
ARG BASE_IMAGE=rocker/shiny:latest
FROM ${BASE_IMAGE}

RUN rm -rf /srv/shiny-server/index.html

COPY shiny-customized.conf /etc/shiny-server/shiny-server.conf
