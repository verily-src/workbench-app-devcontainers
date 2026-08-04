FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by workbench-tools feature
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    pkg-config \
    curl \
    git \
    sed \
    sudo \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
