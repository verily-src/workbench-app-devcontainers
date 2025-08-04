# Use an official Python runtime as a parent image
FROM mcr.microsoft.com/vscode/devcontainers/python:3.11-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install any needed packages specified in requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install cirrocumulus
