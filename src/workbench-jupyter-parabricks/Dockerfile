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

# Set environment variables (optional, for consistency)
ENV JUPYTER_USER=jupyter
ENV JUPYTER_USER_HOME_DIR=/home/jupyter

# Install Jupyter Lab using pip
RUN pip3 install jupyterlab

# Set working directory to jupyter's home
WORKDIR /home/jupyter

# Expose the port Jupyter Lab will run on
EXPOSE 8888

# Switch to jupyter user for running Jupyter
USER jupyter

# Optional: Start Jupyter Lab (if you want to run it directly)
# CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]