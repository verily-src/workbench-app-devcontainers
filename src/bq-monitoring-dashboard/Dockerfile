FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY src/bq-monitoring-dashboard/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create streamlit user with home directory
RUN useradd -m -u 1000 -s /bin/bash streamlit && \
    echo "streamlit ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set working directory
WORKDIR /workspace

# Expose Streamlit port
EXPOSE 8501

# Run Streamlit from workspace
CMD ["streamlit", "run", "/workspace/src/bq-monitoring-dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
