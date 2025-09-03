# Use the official NVIDIA Clara Parabricks container as the base image
FROM nvcr.io/nvidia/clara/clara-parabricks:4.5.1-1

# Switch to root user to install packages and create new user
USER root

# Update package lists and install python3, pip, and other essentials
RUN apt-get update && \
    apt-get install -y python3 python3-pip sudo && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create jupyter user with home directory
RUN useradd -m -s /bin/bash jupyter && \
    echo "jupyter ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/jupyter

RUN mkdir -p /home/jupyter/workspace && \
    chown -R jupyter:jupyter /home/jupyter

# Install Jupyter Lab using pip
RUN pip3 install jupyterlab

# Expose the port Jupyter Lab will run on
EXPOSE 8888

# Switch to jupyter user for running Jupyter
USER root
