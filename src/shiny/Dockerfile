# syntax=docker/dockerfile:1.5-labs
FROM rocker/shiny:latest 

RUN rm -rf /srv/shiny-server/index.html

COPY shiny-customized.conf /etc/shiny-server/shiny-server.conf
