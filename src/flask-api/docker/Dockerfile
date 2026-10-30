FROM python:3.10-slim

# System dependencies (optional: add more as needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

# Copy application code
WORKDIR /workspace/app
COPY app /workspace/app

# Expose Flask app
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]