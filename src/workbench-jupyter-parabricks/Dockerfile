# Use the official NVIDIA Clara Parabricks container as the base image
FROM nvcr.io/nvidia/clara/clara-parabricks:4.5.1-1

# Set the working directory inside the container
WORKDIR /workspace

# Switch to root user to install packages
USER root

# Update package lists and install python3, pip, and other essentials
# Clean up apt-get cache to reduce image size
RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Jupyter Lab using pip
RUN pip3 install jupyterlab

# Expose the port Jupyter Lab will run on
EXPOSE 8888