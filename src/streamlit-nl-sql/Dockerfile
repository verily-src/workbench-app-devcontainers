FROM python:3.11-slim-bookworm

# Install system dependencies needed for Workbench integration
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    fuse \
    tar \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running Streamlit
RUN useradd -m -s /bin/bash -u 1000 streamlit

# Set working directory
WORKDIR /home/streamlit

# Copy requirements and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application code
COPY app/ /home/streamlit/app/

# Change ownership to streamlit user
RUN chown -R streamlit:streamlit /home/streamlit

# Switch to streamlit user
USER streamlit

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Default command (will be overridden in docker-compose)
CMD ["streamlit", "run", "/home/streamlit/app/main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
