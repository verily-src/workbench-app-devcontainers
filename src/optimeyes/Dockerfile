FROM ubuntu:jammy-20230816

# Install essential system packages
RUN apt update -y && \
    apt-get install -y \
    software-properties-common \
    python3.10 \
    python3-pip \
    vim \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.10 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# Set working directory
WORKDIR /workspace

# Copy requirements file
COPY requirements.txt /workspace/requirements.txt

# Copy .env file
COPY .env /OPTIMEyes/.env

# Install Python dependencies
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Create necessary directories
RUN mkdir -p /workspace/flask_server /workspace/data /config

# Expose Flask port
EXPOSE 80

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=OPTIMEyes

# Default command
CMD ["bash"]
