FROM python:3.11-slim

# Install system dependencies required by workbench-tools feature and startup scripts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    pkg-config \
    curl \
    git \
    sed \
    sudo \
    tar \
    default-jre-headless \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Create app user similar to jupyter pattern
RUN useradd -m -s /bin/bash app && \
    echo "app ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /workspace

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set ownership
RUN chown -R app:app /workspace

EXPOSE 8080

CMD ["python", "app.py"]
